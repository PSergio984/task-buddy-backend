"""API endpoints for the gamified focus layer: profile + event ledger sync."""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RATE_LIMIT_GAME_EVENTS, RATE_LIMIT_GAME_READ
from app.crud import game as game_crud
from app.dependencies import get_db
from app.game import engine, service
from app.limiter import limiter
from app.models.game import DiaryEntry, FocusPhase, SessionNote
from app.models.user import User
from app.schemas.game import (
    DiaryEntryIn,
    DiaryEntryRead,
    DiaryEntryUpdate,
    DiaryListResponse,
    GameEventBatch,
    GameEventRead,
    GameEventsFeedResponse,
    GameProfileRead,
    GameSyncResponse,
    RetentionIn,
    SessionNoteIn,
    SessionNoteRead,
    TimelineDayResponse,
    TimelineMarker,
    TimelinePhase,
    TimelineSessionBlock,
)
from app.security import get_confirmed_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/game",
    tags=["game"],
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Not authenticated"},
    },
)


def _to_profile_read(profile, rates) -> GameProfileRead:
    return GameProfileRead.from_profile(profile, engine.xp_to_next_level(profile.level, rates))


@router.get("/profile", response_model=GameProfileRead)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_profile(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameProfileRead:
    """Return the user's game profile, creating the default on first use."""
    profile = await game_crud.get_or_create_profile(db, current_user.id)
    rates = await service.load_rates(db)
    await db.commit()
    return _to_profile_read(profile, rates)


@router.post("/events", response_model=GameSyncResponse)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def post_events(
    batch: GameEventBatch,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameSyncResponse:
    """Apply a batch of queued client events; idempotent per client_event_id."""
    # Hoisted: the create-race path rolls back the session, which expires the
    # eager-loaded User — touching current_user.id afterwards would lazy-load.
    user_id = current_user.id
    try:
        profile, results, rates = await service.ingest_events(db, user_id, batch.events)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    applied = sum(1 for r in results if r.status == "applied")
    logger.info(
        "game events ingested: user=%s applied=%d duplicates=%d",
        user_id,
        applied,
        len(results) - applied,
    )
    return GameSyncResponse(
        profile=_to_profile_read(profile, rates),
        results=results,
        applied=applied,
        duplicates=len(results) - applied,
        server_time=datetime.now(timezone.utc),
    )


@router.get("/events", response_model=GameEventsFeedResponse)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_events(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    since: Annotated[Optional[int], Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> GameEventsFeedResponse:
    """Ledger catchup feed: events with id > `since` (the last id the client saw)."""
    rows = await game_crud.get_events_since(db, current_user.id, since, limit)
    return GameEventsFeedResponse(
        events=[GameEventRead.model_validate(row) for row in rows],
        server_time=datetime.now(timezone.utc),
    )


def _day_window(day: date) -> tuple[datetime, datetime]:
    """The UTC [start, end) instants bounding a calendar day."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


async def _visible_entry(db: AsyncSession, user_id: int, entry_id: int) -> DiaryEntry | None:
    """The owned entry, or None when missing or past the retention horizon."""
    retention = await game_crud.get_retention(db, user_id)
    cutoff = game_crud.retention_cutoff(retention, datetime.now(timezone.utc).date())
    entry = await game_crud.get_diary_entry(db, user_id, entry_id)
    if entry is None or (cutoff is not None and entry.entry_date < cutoff):
        return None
    return entry


@router.post(
    "/diary",
    response_model=DiaryEntryRead,
    status_code=201,
    responses={409: {"description": "A stand-up entry already exists for this date"}},
)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def create_diary_entry(
    entry_in: DiaryEntryIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiaryEntryRead:
    """Create a diary entry: one stand-up per user per UTC day, freeform unlimited."""
    user_id = current_user.id
    entry_date = entry_in.entry_date or datetime.now(timezone.utc).date()
    # A date past the retention horizon would be unreadable the moment it's
    # written — reject at the boundary instead of 409ing on an invisible
    # stand-up or returning an id that instantly 404s.
    retention = await game_crud.get_retention(db, user_id)
    cutoff = game_crud.retention_cutoff(retention, datetime.now(timezone.utc).date())
    if cutoff is not None and entry_date < cutoff:
        raise HTTPException(status_code=400, detail="entry_date is before the retention horizon")
    # Pre-check so the common double-post gets a deterministic 409; the
    # partial unique index (uq_diary_entries_one_standup) is the race backstop.
    if entry_in.kind == "standup" and await game_crud.find_standup(db, user_id, entry_date):
        raise HTTPException(status_code=409, detail="A stand-up entry already exists for this date")
    entry = DiaryEntry(
        user_id=user_id,
        kind=entry_in.kind,
        entry_date=entry_date,
        good=entry_in.good,
        bad=entry_in.bad,
        next=entry_in.next,
        freeform=entry_in.freeform,
    )
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="A stand-up entry already exists for this date"
        ) from exc
    await db.commit()
    logger.info("diary entry created: user=%s entry=%s kind=%s", user_id, entry.id, entry.kind)
    return DiaryEntryRead.model_validate(entry)


@router.get("/diary", response_model=DiaryListResponse)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def list_diary_entries(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    date: Annotated[Optional[date], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DiaryListResponse:
    """Entries newest-first; `date` pins one day. Entries past retention are hidden."""
    retention = await game_crud.get_retention(db, current_user.id)
    cutoff = game_crud.retention_cutoff(retention, datetime.now(timezone.utc).date())
    # limit+1 rows: the extra row is the has_more signal, not a real read.
    rows = await game_crud.list_diary_entries(
        db, current_user.id, date, cutoff, limit=limit + 1, offset=offset
    )
    return DiaryListResponse(
        entries=[DiaryEntryRead.model_validate(row) for row in rows[:limit]],
        has_more=len(rows) > limit,
    )


@router.get(
    "/diary/{entry_id}",
    response_model=DiaryEntryRead,
    responses={404: {"description": "Diary entry not found"}},
)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_diary_entry(
    entry_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiaryEntryRead:
    entry = await _visible_entry(db, current_user.id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Diary entry not found")
    return DiaryEntryRead.model_validate(entry)


@router.patch(
    "/diary/{entry_id}",
    response_model=DiaryEntryRead,
    responses={
        400: {"description": "No fields to update"},
        404: {"description": "Diary entry not found"},
    },
)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def update_diary_entry(
    entry_id: int,
    entry_in: DiaryEntryUpdate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiaryEntryRead:
    update_data = entry_in.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    entry = await _visible_entry(db, current_user.id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Diary entry not found")
    # The patch merges over existing fields — reject if the result would be
    # an empty row (create validates non-empty; update must hold the line).
    merged = {
        field: update_data.get(field, getattr(entry, field))
        for field in ("good", "bad", "next", "freeform")
    }
    if not any(merged.values()):
        raise HTTPException(
            status_code=400,
            detail="Entry must keep at least one of good/bad/next/freeform",
        )
    for field, value in update_data.items():
        setattr(entry, field, value)
    await db.commit()
    # updated_at is an onupdate column — expired post-commit, refetch it.
    await db.refresh(entry)
    logger.info("diary entry updated: user=%s entry=%s", current_user.id, entry.id)
    return DiaryEntryRead.model_validate(entry)


@router.delete(
    "/diary/{entry_id}",
    responses={404: {"description": "Diary entry not found"}},
)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def delete_diary_entry(
    entry_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    entry = await _visible_entry(db, current_user.id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Diary entry not found")
    await db.delete(entry)
    await db.commit()
    logger.info("diary entry deleted: user=%s entry=%s", current_user.id, entry_id)
    return {"message": "Diary entry deleted successfully"}


@router.post(
    "/sessions/{session_id}/note",
    response_model=SessionNoteRead,
    status_code=201,
    responses={
        404: {"description": "Focus session not found"},
        409: {"description": "A note already exists for this session"},
    },
)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def attach_session_note(
    session_id: int,
    note_in: SessionNoteIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionNoteRead:
    """Attach the end-of-session reflection note; one per session, owner only."""
    user_id = current_user.id
    session = await game_crud.get_focus_session(db, session_id, user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Focus session not found")
    # Pre-check for the common retry; uq_session_notes_one_per_session is the
    # race backstop (session_id is NULL after its session is deleted).
    if await game_crud.find_session_note(db, session_id) is not None:
        raise HTTPException(status_code=409, detail="A note already exists for this session")
    note = SessionNote(user_id=user_id, session_id=session_id, content=note_in.content)
    db.add(note)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="A note already exists for this session"
        ) from exc
    await db.commit()
    logger.info("session note created: user=%s session=%s", user_id, session_id)
    return SessionNoteRead.model_validate(note)


@router.get(
    "/sessions/{session_id}/note",
    response_model=SessionNoteRead,
    responses={404: {"description": "Focus session or note not found"}},
)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_session_note(
    session_id: int,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionNoteRead:
    """Fetch the note attached to a session — owner only, 404 without one."""
    session = await game_crud.get_focus_session(db, session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Focus session not found")
    note = await game_crud.find_session_note(db, session_id)
    if note is None:
        raise HTTPException(status_code=404, detail="No note for this session")
    return SessionNoteRead.model_validate(note)


@router.get("/timeline", response_model=TimelineDayResponse)
@limiter.limit(RATE_LIMIT_GAME_READ)
async def get_timeline(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    date: Annotated[Optional[date], Query()] = None,
) -> TimelineDayResponse:
    """Merged day view: focus sessions as time-axis blocks, ledger events as
    point markers, and the day's diary entries — one shape for the UI."""
    user_id = current_user.id
    today = datetime.now(timezone.utc).date()
    day = date or today
    # The widened query bounds span day±2 — extreme dates would OverflowError.
    if not (day.min + timedelta(days=1) <= day <= day.max - timedelta(days=2)):
        raise HTTPException(status_code=400, detail="date out of supported range")
    retention = await game_crud.get_retention(db, user_id)
    cutoff = game_crud.retention_cutoff(retention, today)

    sessions: list[TimelineSessionBlock] = []
    markers: list[TimelineMarker] = []
    diary: list[DiaryEntryRead] = []
    # A day entirely past the retention horizon reads as empty — nothing else
    # in the response needs row-level filtering since it all belongs to `day`.
    if cutoff is None or day >= cutoff:
        start, end = _day_window(day)
        session_rows = await game_crud.get_sessions_started_between(db, user_id, start, end)
        phase_rows = await game_crud.get_phases_for_sessions(db, [s.id for s in session_rows])
        phases_by_session: dict[int, list[FocusPhase]] = {}
        for phase in phase_rows:
            phases_by_session.setdefault(phase.session_id, []).append(phase)
        now = datetime.now(timezone.utc)
        sessions = [
            TimelineSessionBlock(
                id=s.id,
                mode=s.mode,
                status=s.status,
                task_id=s.task_id,
                activity_label=s.activity_label,
                # SQLite reads tz columns back naive — normalize before the
                # subtraction (an active session's None ended_at falls back to
                # aware `now` and a naive-aware mix raises TypeError).
                started_at=game_crud.utc_aware(s.started_at),
                ended_at=game_crud.utc_aware(s.ended_at) if s.ended_at else None,
                duration_seconds=int(
                    (
                        (game_crud.utc_aware(s.ended_at) if s.ended_at else now)
                        - game_crud.utc_aware(s.started_at)
                    ).total_seconds()
                ),
                phases=[TimelinePhase.model_validate(p) for p in phases_by_session.get(s.id, [])],
            )
            for s in session_rows
        ]
        markers = [
            TimelineMarker(
                id=e.id,
                type=e.type,
                ts=game_crud.utc_aware(e.client_ts),
                outcome=e.payload.get("_outcome"),
            )
            for e in await game_crud.get_events_between(db, user_id, start, end)
        ]
        diary = [
            DiaryEntryRead.model_validate(row)
            for row in await game_crud.list_diary_entries(db, user_id, day, cutoff)
        ]

    return TimelineDayResponse(
        date=day,
        sessions=sessions,
        markers=markers,
        diary=diary,
        server_time=datetime.now(timezone.utc),
    )


@router.patch("/profile/retention", response_model=GameProfileRead)
@limiter.limit(RATE_LIMIT_GAME_EVENTS)
async def update_retention(
    retention_in: RetentionIn,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_confirmed_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameProfileRead:
    """Set the diary/timeline read horizon: 90d, 1y, or forever."""
    profile = await game_crud.get_or_create_profile(db, current_user.id)
    profile.retention = retention_in.retention
    await db.commit()
    rates = await service.load_rates(db)
    return _to_profile_read(profile, rates)
