"""API tests for the phone-down focus overlay (#70).

Same conventions as test_game_speedrun/test_game_sessions: rewind row
timestamps, let the next call's wall-clock evaluation replay transitions,
and report spans/violations through /game/events batches.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as game_crud
from app.game import session_service
from app.models.game import FocusPhase, FocusSession, GameEvent
from app.models.user import User

SESSIONS = "/api/v1/game/sessions"
EVENTS = "/api/v1/game/events"


@pytest.fixture(autouse=True)
def _seeded_rng(monkeypatch) -> None:
    """Deterministic crit rolls: seed 0's early draws stay above crit chance."""
    import random

    monkeypatch.setattr(session_service, "_rng", random.Random(0))
    import app.game.service as svc

    monkeypatch.setattr(svc, "_rng", random.Random(0))


def _ago(seconds: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _start(client: AsyncClient, phone: bool = True, **overrides) -> dict:
    body = {
        "mode": "timer",
        "phases": [{"kind": "focus", "minutes": 10}],
        "phone_down": phone,
        **overrides,
    }
    response = await client.post(SESSIONS, json=body)
    assert response.status_code == 201, response.text
    return response.json()["session"]


async def _rewind_phase(db: AsyncSession, session_id: int, seconds: int, seq: int = 0) -> None:
    await db.execute(
        update(FocusPhase)
        .where(FocusPhase.session_id == session_id, FocusPhase.seq == seq)
        .values(started_at=_ago(seconds))
    )
    await db.commit()


async def _rewind_session(db: AsyncSession, session_id: int, seconds: int) -> None:
    """Backdate just the session's started_at — keeps fixture chronology
    plausible (violation at_ts values inside the session's lifetime)."""
    await db.execute(
        update(FocusSession).where(FocusSession.id == session_id).values(started_at=_ago(seconds))
    )
    await db.commit()


async def _end_session_started_ago(db: AsyncSession, session_id: int, seconds: int) -> None:
    """Rewind session + phase so a 10-min phase is long past; the next
    request's evaluation ends the session."""
    await db.execute(
        update(FocusSession).where(FocusSession.id == session_id).values(started_at=_ago(seconds))
    )
    await _rewind_phase(db, session_id, seconds)


def _span(
    eid: str,
    session_id: int,
    start_ago: int = 20 * 60,
    end_ago: int = 0,
    claimed: str = "verified",
    evidence: str = "live",
) -> dict:
    """A span covering the whole rewound (15-min) phase window by default —
    wall-clock outside every span counts as unverified, so full coverage is
    the baseline for the verified-pay tests."""
    return {
        "client_event_id": eid,
        "type": "phone_down_span",
        "client_ts": _ago(end_ago).isoformat(),
        "payload": {
            "session_id": session_id,
            "start_ts": _ago(start_ago).isoformat(),
            "end_ts": _ago(end_ago).isoformat(),
            "claimed_tier": claimed,
            "evidence": evidence,
        },
    }


def _violation(eid: str, session_id: int, at_ago: int = 5 * 60, kind: str = "pickup") -> dict:
    return {
        "client_event_id": eid,
        "type": "phone_down_violation",
        "client_ts": _ago(at_ago).isoformat(),
        "payload": {"session_id": session_id, "at_ts": _ago(at_ago).isoformat(), "kind": kind},
    }


def _phase_event(eid: str, session_id: int, at_ago: int = 0, minutes: int = 10, **extra) -> dict:
    """A synced focus_phase_completed — the offline-queue scoring path."""
    return {
        "client_event_id": eid,
        "type": "focus_phase_completed",
        "client_ts": _ago(at_ago).isoformat(),
        "payload": {"minutes": minutes, "session_id": session_id, **extra},
    }


async def _post(client: AsyncClient, events: list[dict]) -> dict:
    response = await client.post(EVENTS, json={"events": events})
    assert response.status_code == 200, response.text
    return response.json()


async def _events(db: AsyncSession, event_type: str) -> list[GameEvent]:
    rows = await db.execute(select(GameEvent).where(GameEvent.type == event_type))
    return list(rows.scalars().all())


async def _last_phase_pay(db: AsyncSession) -> tuple[dict, dict]:
    """(outcome, phone_down block) of the newest focus_phase_completed row —
    per-event pay is what these tests pin; profile totals accumulate."""
    row = sorted(await _events(db, "focus_phase_completed"), key=lambda e: e.id)[-1]
    return row.payload["_outcome"], row.payload["phone_down"]


async def _blob(db: AsyncSession, session_id: int) -> dict:
    row = (await db.execute(select(FocusSession).where(FocusSession.id == session_id))).scalar_one()
    return row.phone_down


async def _verified_phone_session(client: AsyncClient, db: AsyncSession, tag: str) -> dict:
    """One completed all-verified phone-down session (ended status)."""
    session = await _start(client, phone=True)
    sid = session["id"]
    await _end_session_started_ago(db, sid, 15 * 60)
    await _post(client, [_span(f"{tag}-span", sid)])
    r = await client.get(f"{SESSIONS}/{sid}")
    assert r.json()["session"]["status"] == "ended"
    return r.json()


class TestStart:
    async def test_phone_down_initializes_blob(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=True)
        # The API strips server-internal bookkeeping — the client's blob
        # copy carries only what end cards/history render.
        assert session["phone_down"] == {
            "enabled": True,
            "spans": [],
            "violations": 0,
        }
        # Internals still persist on the stored blob (dedupe belt + charge
        # bookkeeping must survive — they're just not API-served).
        blob = await _blob(db, session["id"])
        assert blob["penalized_violation_ats"] == []
        assert blob["reported_client_event_ids"] == []
        started = (await _events(db, "session_started"))[0]
        assert started.payload["phone_down"]["enabled"] is True

    async def test_default_leaves_blob_null(self, authenticated_async_client: AsyncClient) -> None:
        session = await _start(authenticated_async_client, phone=False)
        assert session["phone_down"] is None

    @pytest.mark.parametrize(
        "body",
        [
            {
                "mode": "speedrun",
                "phone_down": True,
                "speedrun": {"kind": "time_boxed", "budget_minutes": 10},
            },
            {
                "mode": "speedrun",
                "phone_down": True,
                "activity_label": "5k",
                "speedrun": {"kind": "beat_best"},
            },
        ],
    )
    async def test_phone_down_plus_speedrun_is_400(
        self, authenticated_async_client: AsyncClient, body: dict
    ) -> None:
        """One special overlay per session — speedrun is server-judged
        online-only while phone-down tolerates offline evidence."""
        r = await authenticated_async_client.post(SESSIONS, json=body)
        assert r.status_code == 400, r.text

    async def test_phone_down_plus_stopwatch_is_400(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        """Stopwatch pays milestone XP, not per-minute — no paid minute
        stream to tier-weight, so the overlay could only farm streaks."""
        r = await authenticated_async_client.post(
            SESSIONS, json={"mode": "stopwatch", "phone_down": True}
        )
        assert r.status_code == 400, r.text


class TestSpanIngest:
    async def test_valid_span_appends_adjudicated(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _post(authenticated_async_client, [_span("sp-1", sid)])
        blob = await _blob(db, sid)
        assert len(blob["spans"]) == 1
        span = blob["spans"][0]
        assert span["tier"] == "verified"
        assert span["evidence"] == "live"
        assert blob["reported_client_event_ids"] == ["sp-1"]

    async def test_retry_is_idempotent(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        batch = {"events": [_span("sp-1", sid)]}
        r1 = await authenticated_async_client.post(EVENTS, json=batch)
        assert r1.json()["applied"] == 1
        r2 = await authenticated_async_client.post(EVENTS, json=batch)
        assert r2.json()["duplicates"] == 1
        blob = await _blob(db, sid)
        assert len(blob["spans"]) == 1

    async def test_unknown_session_records_unscored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        await _post(authenticated_async_client, [_span("sp-x", session["id"] + 999)])
        blob = await _blob(db, session["id"])
        assert blob["spans"] == []
        row = (await _events(db, "phone_down_span"))[0]
        assert row.payload["_outcome"]["scored"] is False
        assert row.payload["_outcome"]["reason"] == "session_unresolvable"

    async def test_foreign_session_records_unscored(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        # Register + confirm a second user and post as them.
        await authenticated_async_client.post(
            "/api/v1/users/register",
            json={"username": "other", "email": "other@example.com", "password": "otherpassword"},
        )
        await db.execute(
            update(User).where(User.email == "other@example.com").values(confirmed=True)
        )
        await db.commit()
        token = (
            await authenticated_async_client.post(
                "/api/v1/users/token",
                data={"username": "other@example.com", "password": "otherpassword"},
            )
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        r = await authenticated_async_client.post(
            EVENTS, json={"events": [_span("sp-f", session["id"])]}, headers=headers
        )
        assert r.status_code == 200, r.text
        blob = await _blob(db, session["id"])
        assert blob["spans"] == []
        row = (await _events(db, "phone_down_span"))[0]
        assert row.payload["_outcome"]["reason"] == "session_unresolvable"

    async def test_non_phone_down_session_rejects(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=False)
        await _post(authenticated_async_client, [_span("sp-1", session["id"])])
        row = (await _events(db, "phone_down_span"))[0]
        assert row.payload["_outcome"]["reason"] == "phone_down_not_enabled"

    async def test_end_before_start_rejected(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        await _post(
            authenticated_async_client,
            [_span("sp-bad", session["id"], start_ago=60, end_ago=10 * 60)],
        )
        blob = await _blob(db, session["id"])
        assert blob["spans"] == []
        row = (await _events(db, "phone_down_span"))[0]
        assert row.payload["_outcome"]["reason"] == "invalid_span"

    async def test_evidence_none_forces_unverified(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        await _post(
            authenticated_async_client,
            [_span("sp-1", session["id"], claimed="verified", evidence="none")],
        )
        blob = await _blob(db, session["id"])
        assert blob["spans"][0]["tier"] == "unverified"

    async def test_claimed_violated_adjudicates_violated(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        await _post(
            authenticated_async_client,
            [_span("sp-1", session["id"], claimed="violated")],
        )
        blob = await _blob(db, session["id"])
        assert blob["spans"][0]["tier"] == "violated"

    async def test_violation_in_window_adjudicates_violated(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A span whose window contains a reported violation instant is
        violated even when the client claims verified."""
        session = await _start(authenticated_async_client)
        sid = session["id"]
        # Keep the fixture chronology plausible (start predates evidence).
        await _rewind_session(db, sid, 20 * 60)
        await _post(
            authenticated_async_client,
            [_violation("v-1", sid, at_ago=6 * 60), _span("sp-1", sid)],
        )
        blob = await _blob(db, sid)
        assert blob["violations"] == 1
        assert blob["spans"][0]["tier"] == "violated"

    async def test_retro_evidence_honors_verified_claim(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Retroactive sensor-recording proof (e.g. iOS CMSensorRecorder)
        honors a claimed verified tier — only evidence "none" forces
        unverified."""
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [_span("sp-1", sid, claimed="verified", evidence="retro")],
        )
        blob = await _blob(db, sid)
        assert blob["spans"][0]["tier"] == "verified"
        assert blob["spans"][0]["evidence"] == "retro"

    async def test_span_cap_rejects_over_limit(
        self, authenticated_async_client: AsyncClient, db: AsyncSession, monkeypatch
    ) -> None:
        """Over MAX_SPANS_PER_SESSION the span records unscored and the
        blob stops growing — an unbounded list would inflate the row."""
        import app.game.service as svc

        monkeypatch.setattr(svc, "MAX_SPANS_PER_SESSION", 2)
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [_span("sp-1", sid), _span("sp-2", sid), _span("sp-3", sid)],
        )
        blob = await _blob(db, sid)
        assert len(blob["spans"]) == 2
        capped = [e for e in await _events(db, "phone_down_span") if e.client_event_id == "sp-3"]
        assert capped[0].payload["_outcome"]["reason"] == "span_cap_reached"

    async def test_violation_event_increments_and_validates(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                _violation("v-1", sid),
                _violation("v-2", sid),
                _violation("v-bad", sid, kind="polite_boop"),
            ],
        )
        blob = await _blob(db, sid)
        assert blob["violations"] == 2
        bad = [e for e in await _events(db, "phone_down_violation") if e.client_event_id == "v-bad"]
        assert bad[0].payload["_outcome"]["reason"] == "invalid_kind"


class TestScoring:
    async def test_verified_full_pay_inline(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(authenticated_async_client, [_span("sp-1", sid)])
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["session"]["status"] == "ended"
        # 10 min x 1 XP/min, easy, streak 0 -> 10 XP, 2 gold.
        assert body["profile"]["xp_today"] == 10
        assert body["profile"]["gold_today"] == pytest.approx(2.0)
        row = (await _events(db, "focus_phase_completed"))[0]
        block = row.payload["phone_down"]
        assert block["verified_minutes"] == pytest.approx(10.0, rel=0.05)
        assert block["xp_multiplier"] == 1.0

    async def test_unverified_half_pay(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [_span("sp-1", sid, claimed="unverified", evidence="retro")],
        )
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["profile"]["xp_today"] == 5  # 10 x 0.5
        assert body["profile"]["gold_today"] == pytest.approx(1.0)  # ceil(5*0.2)

    async def test_uncovered_counts_unverified(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """No spans at all -> whole phase is unverified (unprovable)."""
        session = await _start(authenticated_async_client, phone=True)
        await _end_session_started_ago(db, session["id"], 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{session['id']}")).json()
        assert body["profile"]["xp_today"] == 5

    async def test_mixed_coverage(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """6 verified + 4 unverified minutes -> 6 x 1 + 4 x 0.5 = 8 XP."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        # The 10-min rewound phase is [15,5]min ago; the span covers its
        # first 6 minutes -> 6 x 1 + 4 x 0.5 = exactly 8 XP (payout floors).
        await _post(
            authenticated_async_client,
            [_span("sp-1", sid, start_ago=15 * 60, end_ago=9 * 60)],
        )
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["profile"]["xp_today"] == 8

    async def test_violated_span_pays_zero(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [_span("sp-1", sid, claimed="violated")],
        )
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["profile"]["xp_today"] == 0
        assert body["profile"]["gold_today"] == pytest.approx(0.0)

    async def test_violated_dominates_claimed_verified_overlap(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A verified-claimed span overlapping a violated span pays the
        overlap as violated — violations dominate coverage, so a client
        can't launder violated minutes into full pay with a verified claim."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                # Verified claim over the whole ~10-min phase window;
                # violated over its second half.
                _span("sp-ok", sid, claimed="verified"),
                _span("sp-bad", sid, claimed="violated", start_ago=10 * 60),
            ],
        )
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        # 5 verified + 5 violated -> 5 XP; the buggy verified-wins order
        # would pay the overlap as verified for 10 XP.
        assert body["profile"]["xp_today"] == 5
        _, block = await _last_phase_pay(db)
        assert block["verified_minutes"] == pytest.approx(5.0, rel=0.05)
        assert block["violated_minutes"] == pytest.approx(5.0, rel=0.05)

    async def test_late_violation_re_adjudicates_stored_span(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A violation whose client_ts orders AFTER its overlapping span
        still downgrades it — violations dominate absolutely, not by upload
        order. The span applies first (verified claim), then the violation
        lands and rewrites the stored tier."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                # Span covers the whole phase; both apply before the
                # violation because client_ts orders it first.
                _span("sp-1", sid, claimed="verified"),
                {
                    "client_event_id": "v-late",
                    "type": "phone_down_violation",
                    # Applied AFTER the span (client_ts is now) while its
                    # at_ts sits inside the span window.
                    "client_ts": _ago(0).isoformat(),
                    "payload": {
                        "session_id": sid,
                        "at_ts": _ago(5 * 60).isoformat(),
                        "kind": "pickup",
                    },
                },
            ],
        )
        blob = await _blob(db, sid)
        tiers = [s.get("tier") for s in blob.get("spans", [])]
        assert tiers == ["violated"]
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["profile"]["xp_today"] == 0

    async def test_late_violation_re_adjudicates_unverified_span(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Unverified spans downgrade too — ingest-time adjudication sends
        violation-in-window to violated for ANY claim, so a late violation
        must not leave an unverified span paying the 0.5x factor."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                _span("sp-1", sid, claimed="unverified", evidence="none"),
                {
                    "client_event_id": "v-late",
                    "type": "phone_down_violation",
                    "client_ts": _ago(0).isoformat(),
                    "payload": {
                        "session_id": sid,
                        "at_ts": _ago(5 * 60).isoformat(),
                        "kind": "pickup",
                    },
                },
            ],
        )
        blob = await _blob(db, sid)
        tiers = [s.get("tier") for s in blob.get("spans", [])]
        assert tiers == ["violated"]

    async def test_first_violation_no_hp_loss(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [_span("sp-1", sid, claimed="verified"), _violation("v-1", sid)],
        )
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["profile"]["hp"] == body["profile"]["max_hp"]
        # The violation still surfaces on the blob for the warning UI.
        assert body["session"]["phone_down"]["violations"] == 1
        assert await _events(db, "damage") == []

    async def test_second_violation_in_window_costs_hp(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                _span("sp-1", sid),
                _violation("v-1", sid, at_ago=8 * 60),
                _violation("v-2", sid, at_ago=6 * 60),
            ],
        )
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["profile"]["hp"] < body["profile"]["max_hp"]
        damage = await _events(db, "damage")
        assert len(damage) == 1
        assert damage[0].payload["reason"] == "phone_down_violations"
        assert damage[0].client_event_id.startswith("server:")

    async def test_sync_path_applies_unverified_weight(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A synced focus_phase_completed on an enabled session pays by the
        adjudicated coverage — unverified minutes earn the factor, so the
        offline queue can't launder full pay."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                _span("sp-1", sid, claimed="unverified", evidence="retro"),
                _phase_event("fp-1", sid),
            ],
        )
        row = (await _events(db, "focus_phase_completed"))[0]
        block = row.payload["phone_down"]
        assert block["verified_minutes"] == 0.0
        assert block["unverified_minutes"] == pytest.approx(10.0, rel=0.05)
        profile = (await authenticated_async_client.get("/api/v1/game/profile")).json()
        assert profile["xp_today"] == 5  # 10 x 0.5 unverified factor

    async def test_forged_phone_down_block_is_recomputed(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A client-supplied phone_down weight block never reaches scoring:
        for an enabled session the server recomputes it — a forged
        multiplier/verified minutes can't self-award verified pay."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                _phase_event(
                    "fp-1",
                    sid,
                    phone_down={
                        "verified_minutes": 10.0,
                        "unverified_minutes": 0.0,
                        "violated_minutes": 0.0,
                        "streak_count": 99,
                        "xp_multiplier": 50.0,
                    },
                )
            ],
        )
        row = (await _events(db, "focus_phase_completed"))[0]
        block = row.payload["phone_down"]
        # Stored row carries the server weights only — the forged values
        # never reached the engine or the ledger.
        assert block["xp_multiplier"] == 1.0
        assert block["streak_count"] == 0
        assert block["verified_minutes"] == 0.0
        assert block["unverified_minutes"] == pytest.approx(10.0, rel=0.05)
        # And the payout is the honest unverified factor, not the forged 50x.
        profile = (await authenticated_async_client.get("/api/v1/game/profile")).json()
        assert profile["xp_today"] == 5

    async def test_forged_block_on_plain_session_is_stripped(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A phone_down block aimed at a session without the overlay is
        removed wholesale — the ledger row carries no client weight claim."""
        session = await _start(authenticated_async_client, phone=False)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [
                _phase_event(
                    "fp-1",
                    sid,
                    phone_down={
                        "verified_minutes": 10.0,
                        "unverified_minutes": 0.0,
                        "violated_minutes": 0.0,
                        "streak_count": 99,
                        "xp_multiplier": 50.0,
                    },
                )
            ],
        )
        row = (await _events(db, "focus_phase_completed"))[0]
        assert "phone_down" not in row.payload
        profile = (await authenticated_async_client.get("/api/v1/game/profile")).json()
        assert profile["xp_today"] == 10

    async def test_sync_penalty_damage_row_hashed_eid(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """The sync-path repeat-violation penalty emits one server-authored
        damage row; the derived eid hashes the client eid (unbounded
        length) instead of truncating it into a collision risk."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _rewind_session(db, sid, 20 * 60)
        await _post(
            authenticated_async_client,
            [
                _violation("v-1", sid, at_ago=8 * 60),
                _violation("v-2", sid, at_ago=6 * 60),
                _phase_event("fp-pen", sid),
            ],
        )
        damage = await _events(db, "damage")
        assert len(damage) == 1
        assert damage[0].payload["reason"] == "phone_down_violations"
        assert damage[0].payload["session_id"] == sid
        expected = "server:s{}:phone_down_hp:sync:{}".format(
            sid,
            hashlib.sha1(b"fp-pen", usedforsecurity=False).hexdigest()[:16],
        )
        assert damage[0].client_event_id == expected

    async def test_penalty_fires_once_per_new_violation(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Repeat scoring calls over the same violation history don't
        re-fine: two in-window violations cost one HP hit total, and a
        later third in-window violation costs exactly one more."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _rewind_session(db, sid, 20 * 60)
        await _post(
            authenticated_async_client,
            [
                _violation("v-1", sid, at_ago=8 * 60),
                _violation("v-2", sid, at_ago=6 * 60),
                _phase_event("fp-1", sid),
            ],
        )
        assert len(await _events(db, "damage")) == 1
        # A second scoring call over the same history does not re-fire.
        await _post(authenticated_async_client, [_phase_event("fp-2", sid)])
        assert len(await _events(db, "damage")) == 1
        # One NEW in-window violation -> exactly one more hit.
        await _post(
            authenticated_async_client,
            [_violation("v-3", sid, at_ago=2 * 60), _phase_event("fp-3", sid)],
        )
        assert len(await _events(db, "damage")) == 2
        blob = await _blob(db, sid)
        # Only the two actually-charged instants are recorded — the exempt
        # earliest is exempt positionally, not permanently.
        assert len(blob["penalized_violation_ats"]) == 2

    async def test_new_violations_charge_per_violation_one_row(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Three NEW in-window violations past the first cost 3 x
        hp_loss_base in ONE damage row — per-violation pricing, not a
        flat one-per-scoring-call fine."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _rewind_session(db, sid, 20 * 60)
        # The window's first violation is warning-only — no damage row.
        await _post(
            authenticated_async_client,
            [_violation("v-1", sid, at_ago=9 * 60), _phase_event("fp-1", sid)],
        )
        assert await _events(db, "damage") == []
        # Three new in-window instants -> one row charging 3 x base (2.0).
        await _post(
            authenticated_async_client,
            [
                _violation("v-2", sid, at_ago=7 * 60),
                _violation("v-3", sid, at_ago=5 * 60),
                _violation("v-4", sid, at_ago=3 * 60),
                _phase_event("fp-2", sid),
            ],
        )
        damage = await _events(db, "damage")
        assert len(damage) == 1
        assert damage[0].payload["reason"] == "phone_down_violations"
        assert damage[0].payload["amount"] == pytest.approx(6.0)
        assert len(damage[0].payload["charged_ats"]) == 3
        assert damage[0].payload["_outcome"]["hp_lost"] == pytest.approx(6.0)

    async def test_cross_session_repeat_window_charges_hp(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """The repeat window is user-wide: a violation on session A inside
        24h makes session B's first violation the 2nd in-window — B's
        scoring charges HP. Rescoring B doesn't double-charge the instant."""
        session_a = await _start(authenticated_async_client, phone=True)
        sid_a = session_a["id"]
        await _rewind_session(db, sid_a, 20 * 60)
        await _post(authenticated_async_client, [_violation("v-a", sid_a, at_ago=8 * 60)])
        # Session A's scoring sees one in-window violation -> warning only.
        await _post(authenticated_async_client, [_phase_event("fp-a", sid_a)])
        assert await _events(db, "damage") == []
        await _end_session_started_ago(db, sid_a, 15 * 60)
        await authenticated_async_client.get(f"{SESSIONS}/{sid_a}")
        # Session B's first violation is the user's 2nd inside 24h.
        session_b = await _start(authenticated_async_client, phone=True)
        sid_b = session_b["id"]
        await _post(
            authenticated_async_client,
            [_violation("v-b", sid_b), _phase_event("fp-b", sid_b)],
        )
        damage = await _events(db, "damage")
        assert len(damage) == 1
        assert damage[0].payload["session_id"] == sid_b
        assert len(damage[0].payload["charged_ats"]) == 1
        # Rescore — the charged_ats row plus the blob both say already paid.
        await _post(authenticated_async_client, [_phase_event("fp-b2", sid_b)])
        assert len(await _events(db, "damage")) == 1

    async def test_violation_outside_window_no_penalty(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A violation whose at_ts falls outside the 24h repeat window
        doesn't count toward the HP penalty — it still lands on the blob."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _rewind_session(db, sid, 20 * 60)
        old = {
            "client_event_id": "v-old",
            "type": "phone_down_violation",
            # Reported recently, but the violation instant is >24h before
            # scoring — outside the window.
            "client_ts": _ago(30).isoformat(),
            "payload": {
                "session_id": sid,
                "at_ts": _ago(25 * 3600).isoformat(),
                "kind": "pickup",
            },
        }
        await _post(
            authenticated_async_client,
            [old, _violation("v-1", sid, at_ago=60), _phase_event("fp-1", sid)],
        )
        assert await _events(db, "damage") == []
        blob = await _blob(db, sid)
        assert blob["violations"] == 2

    async def test_aged_out_charges_dont_suppress_future_penalties(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """Charged violations aging out of the 24h window must not absorb
        later charges: with v1/v2 penalized and aged out, a fresh v3/v4
        pair still costs one HP on the repeat violation."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _rewind_session(db, sid, 20 * 60)
        await _post(
            authenticated_async_client,
            [
                _violation("v-1", sid, at_ago=8 * 60),
                _violation("v-2", sid, at_ago=6 * 60),
                _phase_event("fp-1", sid),
            ],
        )
        assert len(await _events(db, "damage")) == 1
        # Score again ~26h later (client_ts is the scoring instant); the
        # first pair aged out, a fresh in-window pair arrives. Past-dated
        # instants only — future-dated at_ts rows are rejected at ingest.
        await _post(
            authenticated_async_client,
            [
                _violation("v-3", sid, at_ago=30 * 3600),
                _violation("v-4", sid, at_ago=28 * 3600),
                _phase_event("fp-2", sid, at_ago=26 * 3600),
            ],
        )
        assert len(await _events(db, "damage")) == 2

    async def test_backdated_client_ts_violation_still_adjudicates(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A violation reported with client_ts before the session's start
        is still visible to adjudication — the ledger bound keys on
        server_ts, so backdating can't hide a violation from its span."""
        session = await _start(authenticated_async_client)
        sid = session["id"]
        await _rewind_session(db, sid, 20 * 60)
        backdated = {
            "client_event_id": "v-back",
            "type": "phone_down_violation",
            # Report instant predates even the (backdated) session start —
            # a client_ts bound would silently drop this row.
            "client_ts": _ago(60 * 60).isoformat(),
            "payload": {
                "session_id": sid,
                "at_ts": _ago(6 * 60).isoformat(),
                "kind": "pickup",
            },
        }
        await _post(authenticated_async_client, [backdated, _span("sp-1", sid)])
        blob = await _blob(db, sid)
        assert blob["violations"] == 1
        assert blob["spans"][0]["tier"] == "violated"

    async def test_future_at_ts_violation_never_penalizes(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A violation instant beyond receipt+skew is rejected AND
        invisible to the penalty scan — a malformed row must not charge
        HP (SQLite's JSON_QUOTE once leaked missing session_id as 'null')."""
        session = await _start(authenticated_async_client)
        sid = session["id"]
        # Future-dated at_ts with a *past* client_ts — the client_ts bound
        # 422s outright, so the future_at_ts service rejection is what's
        # under test here.
        v_f1, v_f2 = (
            _violation("v-f1", sid, at_ago=-(25 * 3600)),
            _violation("v-f2", sid, at_ago=-(25 * 3600 + 60)),
        )
        v_f1["client_ts"] = v_f2["client_ts"] = _ago(60).isoformat()
        await _post(
            authenticated_async_client,
            [v_f1, v_f2, _violation("v-ok", sid, at_ago=6 * 60), _phase_event("fp-1", sid)],
        )
        rows = await _events(db, "phone_down_violation")
        future = [r for r in rows if r.client_event_id.startswith("v-f")]
        assert all(r.payload["_outcome"].get("reason") == "future_at_ts" for r in future)
        # Only the one legit violation lands in the window → warning-only,
        # no damage row (the rejected pair can't reach the ≥2 threshold).
        assert await _events(db, "damage") == []


class TestStreak:
    async def test_verified_streak_multiplier(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """One prior all-verified session -> +10% XP on verified minutes."""
        await _verified_phone_session(authenticated_async_client, db, "s1")
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(authenticated_async_client, [_span("sp-1", sid)])
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["session"]["status"] == "ended"
        # 10 verified minutes x 1.1 streak bonus.
        outcome, block = await _last_phase_pay(db)
        assert outcome["xp"] == 11
        assert block["streak_count"] == 1
        assert block["xp_multiplier"] == pytest.approx(1.1)

    async def test_streak_caps_at_five(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        for i in range(5):
            await _verified_phone_session(authenticated_async_client, db, f"s{i}")
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(authenticated_async_client, [_span("sp-1", sid)])
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        assert body["session"]["status"] == "ended"
        # +50% cap reached: 10 x 1.5 = 15.
        outcome, block = await _last_phase_pay(db)
        assert outcome["xp"] == 15
        assert block["xp_multiplier"] == pytest.approx(1.5)

    async def test_unverified_session_breaks_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        await _verified_phone_session(authenticated_async_client, db, "s1")
        # An all-unverified (evidence none) phone-down session ends.
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(
            authenticated_async_client,
            [_span("sp-1", sid, claimed="unverified", evidence="none")],
        )
        await _end_session_started_ago(db, sid, 15 * 60)
        await authenticated_async_client.get(f"{SESSIONS}/{sid}")
        # The next verified session sees streak 0 — multiplier is flat.
        session3 = await _start(authenticated_async_client, phone=True)
        sid3 = session3["id"]
        await _post(authenticated_async_client, [_span(f"sp-{sid3}", sid3)])
        await _end_session_started_ago(db, sid3, 15 * 60)
        await authenticated_async_client.get(f"{SESSIONS}/{sid3}")
        outcome, _ = await _last_phase_pay(db)
        assert outcome["xp"] == 10

    async def test_non_phone_down_session_breaks_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        await _verified_phone_session(authenticated_async_client, db, "s1")
        # A plain session completes between the two phone-down runs.
        plain = await _start(authenticated_async_client, phone=False)
        await _end_session_started_ago(db, plain["id"], 15 * 60)
        await authenticated_async_client.get(f"{SESSIONS}/{plain['id']}")
        session3 = await _start(authenticated_async_client, phone=True)
        sid3 = session3["id"]
        await _post(authenticated_async_client, [_span(f"sp-{sid3}", sid3)])
        await _end_session_started_ago(db, sid3, 15 * 60)
        await authenticated_async_client.get(f"{SESSIONS}/{sid3}")
        outcome, _ = await _last_phase_pay(db)
        assert outcome["xp"] == 10

    async def test_abandoned_dirty_session_breaks_streak(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """An abandoned session is never a clean run — the streak walk now
        sees abandoned rows (they were invisible under the ended-only
        filter) and a dirty abandon breaks the run."""
        await _verified_phone_session(authenticated_async_client, db, "s1")
        dirty = await _start(authenticated_async_client, phone=True)
        sid = dirty["id"]
        await _post(authenticated_async_client, [_violation("v-1", sid)])
        r = await authenticated_async_client.post(f"{SESSIONS}/{sid}/stop")
        assert r.status_code == 200, r.text
        assert r.json()["session"]["status"] == "abandoned"
        # Streak order is ended_at order: the abandon must sit BETWEEN the
        # clean run (~5min-ago end) and the next run's end (~1min-ago), or
        # the ended_before bound correctly calls it "not preceding".
        await db.execute(
            update(FocusSession).where(FocusSession.id == sid).values(ended_at=_ago(3 * 60))
        )
        await db.commit()
        session3 = await _start(authenticated_async_client, phone=True)
        sid3 = session3["id"]
        await _post(authenticated_async_client, [_span(f"sp-{sid3}", sid3)])
        await _end_session_started_ago(db, sid3, 11 * 60)
        await authenticated_async_client.get(f"{SESSIONS}/{sid3}")
        outcome, _ = await _last_phase_pay(db)
        assert outcome["xp"] == 10


class TestLateSpans:
    async def test_span_after_scoring_records_but_keeps_pay(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """A span arriving after the phase already scored lands on the blob
        for history; the immutable ledger never re-weights."""
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _end_session_started_ago(db, sid, 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{sid}")).json()
        xp_after_scoring = body["profile"]["xp_today"]
        # Uncovered -> unverified: the phase paid 5 already.
        assert xp_after_scoring == 5
        await _post(authenticated_async_client, [_span("sp-late", sid)])
        blob = await _blob(db, sid)
        assert len(blob["spans"]) == 1
        profile = (await authenticated_async_client.get("/api/v1/game/profile")).json()
        assert profile["xp_today"] == 5


class TestRegression:
    async def test_plain_session_payout_unchanged(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        """No overlay -> the old payout path is byte-identical: no
        phone_down key on the ledger row either."""
        session = await _start(authenticated_async_client, phone=False)
        await _end_session_started_ago(db, session["id"], 15 * 60)
        body = (await authenticated_async_client.get(f"{SESSIONS}/{session['id']}")).json()
        assert body["profile"]["xp_today"] == 10
        assert body["profile"]["gold_today"] == pytest.approx(2.0)
        row = (await _events(db, "focus_phase_completed"))[0]
        assert "phone_down" not in row.payload

    async def test_feed_surfaces_phone_events(
        self, authenticated_async_client: AsyncClient, db: AsyncSession
    ) -> None:
        session = await _start(authenticated_async_client, phone=True)
        sid = session["id"]
        await _post(authenticated_async_client, [_span("sp-1", sid), _violation("v-1", sid)])
        feed = (await authenticated_async_client.get(f"{EVENTS}?since=0")).json()
        types = [e["type"] for e in feed["events"]]
        assert "phone_down_span" in types
        assert "phone_down_violation" in types


class TestLockOrder:
    async def test_sessions_locked_before_profile(
        self, authenticated_async_client: AsyncClient, db: AsyncSession, monkeypatch
    ) -> None:
        """Lock-order invariant (Postgres 40P01 guard): ingest locks the
        batch's target session rows BEFORE the profile FOR UPDATE — the
        session→profile order the verb path takes (_locked_session then
        _evaluate), so a sync batch and a verb can't cross-deadlock.
        FOR UPDATE is a no-op on SQLite, so this pins the call order at
        the crud seam rather than provoking a real deadlock."""
        calls: list[str] = []
        orig_lock = game_crud.lock_sessions
        orig_profile = game_crud.get_or_create_profile

        async def spy_lock(db_, user_id_, ids):
            calls.append("sessions")
            return await orig_lock(db_, user_id_, ids)

        async def spy_profile(db_, user_id_, *, for_update=False):
            calls.append("profile_lock" if for_update else "profile_unlock")
            return await orig_profile(db_, user_id_, for_update=for_update)

        monkeypatch.setattr(game_crud, "lock_sessions", spy_lock)
        monkeypatch.setattr(game_crud, "get_or_create_profile", spy_profile)

        session = await _start(authenticated_async_client)
        calls.clear()  # session start touches the profile too — pin ingest only
        await _post(authenticated_async_client, [_span("sp-1", session["id"])])
        # Unlocked ensure-create first (its create-race rollback must not
        # release session locks), then session locks, then the profile FOR
        # UPDATE — the row exists by then so no race path can fire.
        assert calls.index("profile_unlock") < calls.index("sessions")
        assert calls.index("sessions") < calls.index("profile_lock")
