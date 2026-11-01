"""API tests for /api/v1/game session notes + the merged /game/timeline day view."""

from datetime import date, datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.game import DiaryEntry, FocusPhase, FocusSession, GameEvent, SessionNote
from app.models.user import User

GAME = "/api/v1/game"


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=timezone.utc)


def make_session(user_id: int, start: datetime, end: datetime | None, **kw) -> FocusSession:
    return FocusSession(
        user_id=user_id,
        mode=kw.pop("mode", "pomodoro"),
        status=kw.pop("status", "completed" if end else "active"),
        started_at=start,
        ended_at=end,
        **kw,
    )


def make_event(
    user_id: int, ceid: str, type_: str, ts: datetime, outcome: dict | None = None
) -> GameEvent:
    payload = {"_outcome": outcome if outcome is not None else {"scored": True, "xp": 25}}
    return GameEvent(
        user_id=user_id,
        client_event_id=ceid,
        type=type_,
        payload=payload,
        client_ts=ts,
    )


async def second_user(async_client: AsyncClient, db: AsyncSession) -> dict:
    """Register, confirm and log in a second user; return auth headers + id."""
    await async_client.post(
        "/api/v1/users/register",
        json={
            "username": "other",
            "email": "other@example.com",
            "password": "otherpassword",
        },
    )
    await db.execute(update(User).where(User.email == "other@example.com").values(confirmed=True))
    await db.commit()
    login = await async_client.post(
        "/api/v1/users/token",
        data={"username": "other@example.com", "password": "otherpassword"},
    )
    result = await db.execute(select(User).where(User.email == "other@example.com"))
    return {
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        "id": result.scalar_one().id,
    }


class TestSessionNotes:
    async def test_attach_note_to_session(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        today = datetime.now(timezone.utc).date()
        session = make_session(confirmed_user["id"], at(today, 10), at(today, 10, 25))
        db.add(session)
        await db.commit()

        response = await authenticated_async_client.post(
            f"{GAME}/sessions/{session.id}/note", json={"content": "felt locked in"}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["session_id"] == session.id
        assert body["content"] == "felt locked in"

        result = await db.execute(select(SessionNote))
        note = result.scalar_one()
        assert note.user_id == confirmed_user["id"]
        assert note.session_id == session.id

    async def test_one_note_per_session(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        today = datetime.now(timezone.utc).date()
        session = make_session(confirmed_user["id"], at(today, 10), at(today, 10, 25))
        db.add(session)
        await db.commit()

        first = await authenticated_async_client.post(
            f"{GAME}/sessions/{session.id}/note", json={"content": "one"}
        )
        assert first.status_code == 201, first.text
        second = await authenticated_async_client.post(
            f"{GAME}/sessions/{session.id}/note", json={"content": "two"}
        )
        assert second.status_code == 409, second.text

    async def test_note_requires_owned_session(
        self,
        authenticated_async_client: AsyncClient,
        async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        today = datetime.now(timezone.utc).date()
        session = make_session(confirmed_user["id"], at(today, 10), at(today, 10, 25))
        db.add(session)
        await db.commit()

        other = await second_user(async_client, db)
        response = await async_client.post(
            f"{GAME}/sessions/{session.id}/note",
            headers=other["headers"],
            json={"content": "not mine"},
        )
        assert response.status_code == 404, response.text

    async def test_note_on_missing_session_404(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(
            f"{GAME}/sessions/999999/note", json={"content": "hi"}
        )
        assert response.status_code == 404

    async def test_note_content_required(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        today = datetime.now(timezone.utc).date()
        session = make_session(confirmed_user["id"], at(today, 10), at(today, 10, 25))
        db.add(session)
        await db.commit()

        response = await authenticated_async_client.post(
            f"{GAME}/sessions/{session.id}/note", json={"content": "   "}
        )
        assert response.status_code == 422

    async def test_note_requires_auth(
        self, async_client: AsyncClient, confirmed_user: dict, db: AsyncSession
    ) -> None:
        today = datetime.now(timezone.utc).date()
        session = make_session(confirmed_user["id"], at(today, 10), at(today, 10, 25))
        db.add(session)
        await db.commit()
        # Fresh client: `async_client` picked up an auth cookie at registration.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver/"
        ) as anon:
            response = await anon.post(f"{GAME}/sessions/{session.id}/note", json={"content": "hi"})
        assert response.status_code == 401


class TestTimeline:
    async def test_day_view_assembles_blocks_markers_diary(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        day = datetime.now(timezone.utc).date()
        session = make_session(
            confirmed_user["id"],
            at(day, 10),
            at(day, 10, 25),
            activity_label="deep work",
        )
        db.add(session)
        await db.flush()
        db.add_all(
            [
                FocusPhase(
                    session_id=session.id,
                    seq=0,
                    kind="work",
                    status="done",
                    planned_seconds=1500,
                    actual_seconds=1500,
                    started_at=at(day, 10),
                    ended_at=at(day, 10, 25),
                ),
                FocusPhase(
                    session_id=session.id,
                    seq=1,
                    kind="break",
                    status="skipped",
                    planned_seconds=300,
                ),
            ]
        )
        db.add_all(
            [
                make_event(
                    confirmed_user["id"],
                    "e-focus",
                    "focus_phase_completed",
                    at(day, 10, 25),
                    {"scored": True, "xp": 25, "gold": 5},
                ),
                make_event(
                    confirmed_user["id"],
                    "e-hurt",
                    "damage",
                    at(day, 11),
                    {"scored": True, "hp_lost": 2, "died": False},
                ),
            ]
        )
        db.add(
            DiaryEntry(
                user_id=confirmed_user["id"],
                entry_date=day,
                kind="standup",
                good="shipped",
            )
        )
        await db.commit()

        response = await authenticated_async_client.get(f"{GAME}/timeline", params={"date": day})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["date"] == day.isoformat()

        # Sessions arrive as time-axis blocks with start/end/duration + phases.
        assert len(body["sessions"]) == 1
        block = body["sessions"][0]
        assert block["id"] == session.id
        assert block["mode"] == "pomodoro"
        assert block["status"] == "completed"
        assert block["activity_label"] == "deep work"
        assert block["duration_seconds"] == 1500
        assert len(block["phases"]) == 2
        assert block["phases"][0]["kind"] == "work"
        assert block["phases"][0]["actual_seconds"] == 1500
        assert block["phases"][1]["kind"] == "break"

        # Ledger events arrive as point markers carrying type + _outcome.
        assert [m["type"] for m in body["markers"]] == ["focus_phase_completed", "damage"]
        assert body["markers"][0]["outcome"]["xp"] == 25
        assert body["markers"][1]["outcome"]["hp_lost"] == 2
        assert "_outcome" not in body["markers"][0]

        diary = body["diary"]
        assert len(diary) == 1
        assert diary[0]["good"] == "shipped"

    async def test_timeline_defaults_to_today(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.get(f"{GAME}/timeline")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["date"] == datetime.now(timezone.utc).date().isoformat()
        assert body["sessions"] == []
        assert body["markers"] == []
        assert body["diary"] == []

    async def test_timeline_only_returns_the_requested_day(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        day = datetime.now(timezone.utc).date()
        yesterday = day - timedelta(days=1)
        db.add(make_session(confirmed_user["id"], at(yesterday, 9), at(yesterday, 9, 25)))
        db.add(make_event(confirmed_user["id"], "e-old", "damage", at(yesterday, 9, 30)))
        db.add(
            DiaryEntry(
                user_id=confirmed_user["id"],
                entry_date=yesterday,
                kind="freeform",
                freeform="old note",
            )
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(f"{GAME}/timeline", params={"date": day})
        ).json()
        assert body["sessions"] == []
        assert body["markers"] == []
        assert body["diary"] == []

        old = (
            await authenticated_async_client.get(f"{GAME}/timeline", params={"date": yesterday})
        ).json()
        assert len(old["sessions"]) == 1
        assert len(old["markers"]) == 1
        assert len(old["diary"]) == 1

    async def test_timeline_scoped_to_user(
        self,
        authenticated_async_client: AsyncClient,
        async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        day = datetime.now(timezone.utc).date()
        other = await second_user(async_client, db)
        db.add(make_session(other["id"], at(day, 8), at(day, 8, 25)))
        db.add(make_event(other["id"], "e-theirs", "damage", at(day, 8, 30)))
        db.add(DiaryEntry(user_id=other["id"], entry_date=day, kind="standup", good="not yours"))
        await db.commit()

        body = (
            await authenticated_async_client.get(f"{GAME}/timeline", params={"date": day})
        ).json()
        assert body["sessions"] == []
        assert body["markers"] == []
        assert body["diary"] == []

    async def test_timeline_retention_excludes_old_days(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "90d"}
        )
        old_day = datetime.now(timezone.utc).date() - timedelta(days=100)
        db.add(make_session(confirmed_user["id"], at(old_day, 10), at(old_day, 10, 25)))
        db.add(make_event(confirmed_user["id"], "e-old", "damage", at(old_day, 11)))
        db.add(
            DiaryEntry(
                user_id=confirmed_user["id"],
                entry_date=old_day,
                kind="standup",
                good="ancient",
            )
        )
        await db.commit()

        body = (
            await authenticated_async_client.get(f"{GAME}/timeline", params={"date": old_day})
        ).json()
        assert body["sessions"] == []
        assert body["markers"] == []
        assert body["diary"] == []

        # Flipping back to forever surfaces the same rows again.
        await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "forever"}
        )
        body = (
            await authenticated_async_client.get(f"{GAME}/timeline", params={"date": old_day})
        ).json()
        assert len(body["sessions"]) == 1
        assert len(body["markers"]) == 1
        assert len(body["diary"]) == 1

    async def test_timeline_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.get(f"{GAME}/timeline")
        assert response.status_code == 401
