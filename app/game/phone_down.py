"""Phone-down focus overlay (issue #70): adjudication + scoring weights.

TRUST MODEL — orientation evidence is client-claimed. The server stores the
reported facts verbatim and labels each span by its reported evidence class;
it never re-derives orientation. What the server decides honestly is PAY:

- evidence "live" (continuous foreground sensor observation) or "retro"
  (retroactive sensor-recording proof, e.g. iOS CMSensorRecorder) honors the
  client's claimed verified/unverified tier;
- evidence "none" (wall-clock only, no sensor proof) forces unverified
  regardless of the claim;
- a claimed violation, or a span whose window contains a reported violation
  instant (pickup / grace_expired), adjudicates violated and pays nothing.

Blob (FocusSession.phone_down — same JSON pattern as the speedrun column)::

    {"enabled": true,
     "spans": [{"start_ts": iso, "end_ts": iso,
                "tier": "verified"|"unverified"|"violated",   # adjudicated
                "evidence": "live"|"retro"|"none"}],
     "violations": <int>,
     "penalized_violation_ats": [<iso instants already HP-charged>],
     "reported_client_event_ids": [<client_event_id of applied marker events>],
     # written by weight_block at score time for the mobile end card:
     "streak_count": <int>, "xp_multiplier": <float>}

Scoring (where focus_phase_completed computes minutes for an enabled
session): the phase's paid minutes are split across coverage tiers —
violated wins where its span covers, then verified evidence where proven,
then unverified; wall-clock uncovered by any span counts as unverified
(unprovable, not absent). Each tier's minutes pay:
    verified  -> full pay; XP additionally x (1 + min(streak x pct, cap))
    unverified -> x phone_down_unverified_xp_factor
    violated  -> 0
Weighting is proportional (tier minutes = paid minutes x tier seconds /
window seconds), so a pause-stretched wall clock can never mint more than
the phase's paid minutes. Gold takes the same tier weights minus the
streak multiplier — that bonus is XP-only by spec.

Streak: count of consecutive immediately-preceding ended phone_down
sessions whose adjudication is all-verified (>=1 span, every span
verified-tier, violations == 0). Derived at score time by walking recent
ended sessions newest-first — a non-phone-down or non-clean session ends
the run; no stored counter exists to desync.

Violations: the 2nd+ phone_down_violation event for the USER inside
`violation_repeat_window_hours` of the scoring instant costs
`hp_loss_base` HP per NEW in-window violation beyond the first — all
such instants charge in one server-authored damage row. The window is
user-wide, not per-session: a fresh session's violations count recent
ones from earlier sessions, or every session's first violation would be
free forever. The first violation in the window is warning-only — no HP
event; the blob's count feeds the client's warning UI. The penalty row's
`charged_ats` plus the blob's `penalized_violation_ats` record WHICH
instants HP was already charged for — a bare count can't: once charged
violations age out of the window, a stale count would absorb future
charges.

Late-arriving data: spans are adjudicated at ingest, but a violation
event arriving after its span still downgrades the stored tier
(violations dominate absolutely, not by upload order). Spans reported
after a phase already scored are kept on the blob for history but never
retro-adjust pay — the ledger is immutable. The BLOB is not frozen,
though: late spans/violations still land on an ended session's blob and
change what the next session's score-time streak walk and violation
windows see — history adjudicates live, it doesn't replay.

Known limits:
- Covered-time evasion: a client that splits its spans around each
  violation instant leaves no span window containing it, so violated
  minutes shrink toward zero (the violation still counts for streak
  and HP). Inherent to the client-claimed window model — the server
  can only adjudicate the windows it's given.
- Stopwatch mode is rejected at plan time: milestones pay flat XP, not
  per-minute, so there is nothing to tier-weight — the overlay would
  only farm verified streaks on pay it never gated.
"""

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import character_service, engine, notifications
from app.game.engine import GameRates
from app.models.game import FocusSession, GameEvent, GameProfile

VERIFIED, UNVERIFIED, VIOLATED = "verified", "unverified", "violated"
TIERS = (VERIFIED, UNVERIFIED, VIOLATED)
EVIDENCE_LIVE, EVIDENCE_RETRO, EVIDENCE_NONE = "live", "retro", "none"
EVIDENCE_KINDS = (EVIDENCE_LIVE, EVIDENCE_RETRO, EVIDENCE_NONE)
# 'pickup' is proven-movement/external violation evidence only — the
# grace-start pickups the client tracks internally are NOT emitted as
# events; clients report real violations only.
VIOLATION_KINDS = ("pickup", "grace_expired")

SPAN_EVENT = "phone_down_span"
VIOLATION_EVENT = "phone_down_violation"

# Ledger marker emitted when the repeat-violation HP penalty lands.
PENALTY_EVENT = "damage"
PENALTY_REASON = "phone_down_violations"

# Clock-skew slack between an event's claimed instant and its server
# receipt. Bounds violation at_ts at ingest (a violation can't precede
# itself) and widens the penalty scan's server_ts floor, since a legit
# report's server_ts can trail its at_ts by up to this much.
AT_TS_SKEW_SECONDS = 300


def new_blob() -> dict:
    """The enabled-at-start blob shape."""
    return {
        "enabled": True,
        "spans": [],
        "violations": 0,
        "penalized_violation_ats": [],
        "reported_client_event_ids": [],
    }


def enabled_blob(blob: Any) -> bool:
    return isinstance(blob, dict) and blob.get("enabled") is True


def enabled(session: FocusSession) -> bool:
    """Whether the phone-down overlay is on for this session."""
    return enabled_blob(session.phone_down)


def blob_of(session: FocusSession) -> dict:
    """The session's phone_down blob or {} when unset/corrupt — reads
    degrade to the disabled shape rather than crash."""
    return session.phone_down if isinstance(session.phone_down, dict) else {}


def parse_ts(value: Any) -> datetime | None:
    """An ISO-8601 instant as aware UTC; None on anything unparseable.

    Same normalization rule as the ingest schema's client_ts: naive values
    are labeled UTC, aware ones are converted — mixed naive/aware math
    would crash the coverage sort.
    """
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _span_window(span: dict) -> tuple[datetime, datetime] | None:
    start = parse_ts(span.get("start_ts"))
    end = parse_ts(span.get("end_ts"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def adjudicate_tier(claimed_tier: Any, evidence: Any, violation_in_window: bool) -> str | None:
    """The server's stored tier for one reported span; None on bad enums.

    Violations dominate: a self-reported violation or a reported violation
    instant inside the span window forces violated. "none" evidence can
    only ever prove unverified; live/retro honor the client's claim.
    """
    if claimed_tier not in TIERS or evidence not in EVIDENCE_KINDS:
        return None
    if claimed_tier == VIOLATED or violation_in_window:
        return VIOLATED
    if evidence == EVIDENCE_NONE or claimed_tier == UNVERIFIED:
        return UNVERIFIED
    return VERIFIED  # claimed_tier is one of TIERS; only verified remains


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _subtract(
    intervals: list[tuple[datetime, datetime]], minus: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """Merged `intervals` minus the union of `minus` — both inputs merged."""
    out: list[tuple[datetime, datetime]] = []
    for lo, hi in intervals:
        cur = lo
        for m_lo, m_hi in minus:
            if m_hi <= cur:
                continue
            if m_lo >= hi:
                break
            if m_lo > cur:
                out.append((cur, m_lo))
            cur = max(cur, m_hi)
            if cur >= hi:
                break
        if cur < hi:
            out.append((cur, hi))
    return out


def coverage_seconds(spans: Any, w_start: datetime, w_end: datetime) -> dict[str, float]:
    """Unioned coverage per tier inside [w_start, w_end].

    An instant is counted once — precedence: violated wins where its span
    covers, then verified evidence where proven, then unverified. Seconds
    uncovered by any span fold into unverified. Malformed stored spans are
    skipped: a corrupt blob degrades to unverified, never to a crash or a
    free verified claim.
    """
    window = (w_end - w_start).total_seconds()
    if not isinstance(spans, list):
        spans = []
    by_tier: dict[str, list[tuple[datetime, datetime]]] = {t: [] for t in TIERS}
    for span in spans:
        if not isinstance(span, dict) or span.get("tier") not in TIERS:
            continue
        window_of = _span_window(span)
        if window_of is None:
            continue
        lo, hi = max(window_of[0], w_start), min(window_of[1], w_end)
        if lo < hi:
            by_tier[span["tier"]].append((lo, hi))
    # Violations dominate: a verified span overlapping a violated one must
    # pay the overlap as violated — letting the client's verified claim
    # win would launder violated minutes into full pay.
    violated = _merge(by_tier[VIOLATED])
    verified = _subtract(_merge(by_tier[VERIFIED]), violated)
    unverified = _subtract(_merge(by_tier[UNVERIFIED]), _merge(verified + violated))
    seconds = {
        VERIFIED: sum((h - lo).total_seconds() for lo, h in verified),
        VIOLATED: sum((h - lo).total_seconds() for lo, h in violated),
        UNVERIFIED: sum((h - lo).total_seconds() for lo, h in unverified),
    }
    seconds[UNVERIFIED] += max(
        0.0, window - seconds[VERIFIED] - seconds[VIOLATED] - seconds[UNVERIFIED]
    )
    return seconds


def weighted_minutes(
    paid_minutes: float, coverage: dict[str, float], window_seconds: float
) -> dict[str, float]:
    """Paid minutes split per tier, proportional to window coverage.

    A degenerate window (no positive wall-clock) pays everything as
    unverified — the honest class for unprovable time.
    """
    if window_seconds <= 0:
        return {VERIFIED: 0.0, UNVERIFIED: paid_minutes, VIOLATED: 0.0}
    return {t: paid_minutes * coverage.get(t, 0.0) / window_seconds for t in TIERS}


def all_verified(blob: Any) -> bool:
    """The streak predicate: enabled, >=1 span, every span verified-tier,
    zero violations. A span-less session can't claim verified streak —
    zero reported evidence is uncovered-unverified, not verified."""
    if not enabled_blob(blob):
        return False
    try:
        if int(blob.get("violations") or 0) != 0:
            return False
    except (TypeError, ValueError):
        return False  # corrupt count: degrade to not-verified, never crash
    spans = blob.get("spans")
    return (
        isinstance(spans, list)
        and bool(spans)
        and all(isinstance(s, dict) and s.get("tier") == VERIFIED for s in spans)
    )


def verified_streak(prior_blobs: list[Any]) -> int:
    """Consecutive all-verified sessions, newest-first; the first
    non-qualifying session (dirty adjudication, span-less, or not
    phone-down at all) ends the run."""
    streak = 0
    for blob in prior_blobs:
        if not all_verified(blob):
            break
        streak += 1
    return streak


def xp_multiplier(streak: int, rates: GameRates) -> float:
    """1 + min(streak x pct, cap) — the verified-streak XP bonus.

    The bonus additionally clamps at 99: the engine's payload guard
    rejects xp_multiplier > 100, so a misconfigured config cap can never
    wedge every phone-down scoring call into a ValueError.
    """
    return 1.0 + min(
        streak * rates.phone_down_verified_streak_xp_pct,
        rates.phone_down_verified_streak_xp_cap,
        99.0,
    )


def streak_scan_limit(rates: GameRates) -> int:
    """How many recent sessions can still move the multiplier — the bonus
    saturates at cap, so scanning past ceil(cap/pct) can't add credit.
    0 means the bonus is disabled and no query is needed."""
    pct = rates.phone_down_verified_streak_xp_pct
    cap = rates.phone_down_verified_streak_xp_cap
    if pct <= 0 or cap <= 0:
        return 0
    return math.ceil(cap / pct)


async def weight_block(
    db: AsyncSession,
    session: FocusSession,
    *,
    w_start: datetime,
    w_end: datetime,
    paid_minutes: float,
    rates: GameRates,
) -> dict:
    """The focus_phase_completed payload's server-adjudicated phone_down
    block: per-tier paid minutes plus the verified-streak XP multiplier.
    Also records the adjudicated streak on the session blob — callers hold
    the session row lock — so FocusSessionOut.phone_down surfaces the
    streak for end cards and history."""
    blob = blob_of(session)
    coverage = coverage_seconds(blob.get("spans"), w_start, w_end)
    minutes = weighted_minutes(paid_minutes, coverage, (w_end - w_start).total_seconds())
    streak = 0
    limit = streak_scan_limit(rates)
    if limit:
        # "Immediately preceding" means ended before THIS session's own end
        # — sessions finished after the scored one can't inflate a catch-up
        # scoring's streak. A live session has no end yet; the window's own
        # instant (now) is the bound.
        bound = session.ended_at if session.ended_at is not None else w_end
        streak = verified_streak(
            await game_crud.list_recent_ended_phone_blobs(
                db,
                session.user_id,
                exclude_id=session.id,
                limit=limit,
                ended_before=bound,
            )
        )
    mult = xp_multiplier(streak, rates)
    # Reassign like every blob write — the session GET surfaces the
    # adjudicated streak for end cards and history rows.
    session.phone_down = {**blob, "streak_count": streak, "xp_multiplier": mult}
    return {
        "verified_minutes": minutes[VERIFIED],
        "unverified_minutes": minutes[UNVERIFIED],
        "violated_minutes": minutes[VIOLATED],
        "streak_count": streak,
        "xp_multiplier": mult,
    }


def _event_at_ts(e: GameEvent) -> datetime:
    """A violation row's instant: the client-reported at_ts preferred,
    client_ts as fallback for a malformed stored payload."""
    at_ts = parse_ts((e.payload or {}).get("at_ts"))
    return at_ts if at_ts is not None else game_crud.utc_aware(e.client_ts)


async def _violation_events(
    db: AsyncSession, session: FocusSession
) -> list[tuple[datetime, GameEvent]]:
    """(instant, event) pairs of the session's applied violation markers."""
    events = await game_crud.list_phone_down_violation_events(
        db, session.user_id, session.id, session.started_at
    )
    return [(_event_at_ts(e), e) for e in events]


async def violation_covers(
    db: AsyncSession, session: FocusSession, start: datetime, end: datetime
) -> bool:
    """Whether an applied violation instant falls inside [start, end] —
    the 'server sees the violation event' leg of span adjudication."""
    return any(start <= at_ts <= end for at_ts, _ in await _violation_events(db, session))


async def maybe_violation_penalty(
    db: AsyncSession,
    user_id: int,
    session: FocusSession,
    *,
    at: datetime,
    profile: GameProfile,
    rates: GameRates,
    stat_bonus: dict[str, int] | None,
    rng: random.Random,
    eid: str,
    now: datetime | None = None,
) -> dict | None:
    """HP loss per NEW in-window violation past the first — one
    server-authored damage row charging hp_loss_base per newly-charged
    instant (the count of uncharged in-window instants beyond the
    earliest, which stays warning-only). The deterministic eid stays the
    backstop for a lost ledger row — the triggering focus event's own
    idempotency key gates the scoring call.

    The repeat window is user-wide: recent violation rows from earlier
    sessions count, or a fresh session's first violation would be free
    forever (violation farming). The "already charged" set is likewise
    durable: the union of recent penalty rows' `charged_ats` plus the
    blob's `penalized_violation_ats` — the blob half stays the crash
    guard for the window between the blob write and this call's damage
    row landing (a bare count can't work either way: once charged
    violations age out of the window, a stale count would absorb future
    charges).
    """
    window_hours = rates.phone_down_violation_repeat_window_hours
    if window_hours <= 0:
        return None
    # Config is _NONNEGATIVE only — an absurd value would overflow the
    # timedelta subtraction below. Cap at a year: no repeat window can
    # legitimately be longer, and over-charging fails safe.
    window_hours = min(window_hours, 24 * 365)
    received_by = now if now is not None else datetime.now(timezone.utc)
    # `at` is client_ts — a client future-dating every phase claim would
    # slide the whole window past real violations and dodge HP forever.
    # The window can't end past receipt+skew: nothing legit can be claimed
    # about instants that haven't happened yet.
    window_end = min(at, received_by + timedelta(seconds=AT_TS_SKEW_SECONDS))
    floor = window_end - timedelta(hours=window_hours)
    # Receipt bound for the ledger scans: violations that could sit inside
    # [floor, window_end] arrived since the EARLIER of the window floor and
    # window-hours-ago-real — minus another skew, because a row received
    # just under `since` can still hold an instant at-or-above `floor`.
    since = min(floor, received_by - timedelta(hours=window_hours)) - timedelta(
        seconds=AT_TS_SKEW_SECONDS
    )
    # Instants, not events: two markers at the same instant are ONE pickup
    # (a same-ms pair can't be two physical lifts), so the set collapses
    # them — under-charging a forged-timestamp flood is the fail-safe
    # direction; blob["violations"] still counts events for streak/UI.
    in_window_ats = sorted(
        {
            at_ts
            for e in await game_crud.list_recent_phone_down_violations(db, user_id, since)
            if floor <= (at_ts := _event_at_ts(e)) <= window_end
        }
    )
    if len(in_window_ats) < 2:
        return None
    blob = blob_of(session)
    charged_raw = blob.get("penalized_violation_ats")
    charged = set(charged_raw) if isinstance(charged_raw, list) else set()
    # Penalty rows already on the ledger carry the cross-session "fined"
    # set — the blob's own list is session-local and pruned.
    for row in await game_crud.list_recent_phone_down_penalties(db, user_id, since):
        row_ats = (row.payload or {}).get("charged_ats")
        if isinstance(row_ats, list):
            charged.update(row_ats)
    new_ats = [a for a in in_window_ats[1:] if a.isoformat() not in charged]
    if not new_ats:
        return None
    amount = rates.hp_loss_base * len(new_ats)
    hp_before = profile.hp
    outcome = engine.apply_hp_loss(profile, amount, rates, rng, stat_bonus)
    outcome["scored"] = True
    # Reassign like every blob write — plain JSON tracks assignment, and
    # recording the charge BEFORE the damage row lands keeps a crash
    # between them under-, not over-, penalizing. Instants are pruned to
    # 2x the window so the list can't grow forever on a violation-heavy
    # session (aged-out entries can never be charged again anyway), and
    # capped at 100 entries — past that bound the oldest drop off and
    # could re-charge if still in-window (accepted bound; the ledger's
    # charged_ats is the durable set).
    prune_floor = window_end - timedelta(hours=window_hours * 2)
    penalized = sorted(
        s
        # Only instants THIS call (or earlier calls) actually charged —
        # the earliest in-window instant is exempt positionally, not
        # permanently: a belated earlier report must be able to demote it.
        for s in (charged | {a.isoformat() for a in new_ats})
        if (p := parse_ts(s)) is not None and p >= prune_floor
    )[-100:]
    session.phone_down = {**blob, "penalized_violation_ats": penalized}
    await character_service.resolve_death_gear(db, user_id, outcome, rng)
    # `now` is the caller's evaluation/dispatch instant (quiet-hours are
    # checked against it) — not `at`, which can be a backdated event time.
    await notifications.notify_score_outcome(db, user_id, profile, hp_before, outcome, now=now)
    db.add(
        GameEvent(
            user_id=user_id,
            client_event_id=eid,
            type=PENALTY_EVENT,
            client_ts=at,
            payload={
                "session_id": session.id,
                "amount": amount,
                "reason": PENALTY_REASON,
                "violations": len(in_window_ats),
                "charged": len(new_ats),
                # The instants THIS row charged — the durable cross-session
                # "already fined" set future scoring calls union against.
                "charged_ats": [a.isoformat() for a in new_ats],
                "_outcome": outcome,
            },
        )
    )
    # Autoflush is off project-wide: a second session's penalty scan inside
    # the SAME batch must see this row or the instant gets charged twice.
    await db.flush()
    return outcome


# Death-cascade keys a penalty can add to the focus event's stored
# _outcome — merged (not a fresh resolve) so the caller's gear-refresh and
# the ledger both see the hit the phase's scoring caused.
DEATH_KEYS = ("died", "stat_lost", "gear_lost", "gear_lost_key", "hp_lost")


def merge_penalty(outcome: dict, penalty: dict | None) -> None:
    """Fold a fired penalty's death outcome into the scored event's
    outcome — the phase's ledger row then honestly reports that its
    scoring call killed the profile."""
    if penalty is None:
        return
    for key in DEATH_KEYS:
        if key in penalty:
            outcome[key] = penalty[key]
