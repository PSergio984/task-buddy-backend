"""API tests for /api/v1/game/diary — daily stand-up + unlimited freeform entries."""

from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import DiaryEntry
from app.models.user import User

GAME = "/api/v1/game"


def today() -> date:
    return datetime.now(timezone.utc).date()


async def second_user_headers(async_client: AsyncClient, db: AsyncSession) -> dict:
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


class TestDiaryCreate:
    async def test_create_standup_defaults_to_today(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        response = await authenticated_async_client.post(
            f"{GAME}/diary",
            json={"good": "shipped the ledger", "bad": "too many meetings", "next": "rest"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["kind"] == "standup"
        assert body["entry_date"] == today().isoformat()
        assert body["good"] == "shipped the ledger"
        assert body["bad"] == "too many meetings"
        assert body["next"] == "rest"

    async def test_second_standup_same_day_conflicts(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        first = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "a"})
        assert first.status_code == 201, first.text

        second = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "b"})
        assert second.status_code == 409, second.text

    async def test_standup_conflict_uses_entry_date(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        yesterday = (today() - timedelta(days=1)).isoformat()
        first = await authenticated_async_client.post(
            f"{GAME}/diary", json={"entry_date": yesterday, "good": "backfill"}
        )
        assert first.status_code == 201, first.text

        dup = await authenticated_async_client.post(
            f"{GAME}/diary", json={"entry_date": yesterday, "good": "dup"}
        )
        assert dup.status_code == 409, dup.text

    async def test_standup_on_other_days_allowed(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        yesterday = (today() - timedelta(days=1)).isoformat()
        backfill = await authenticated_async_client.post(
            f"{GAME}/diary", json={"entry_date": yesterday, "good": "a"}
        )
        assert backfill.status_code == 201, backfill.text
        current = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "b"})
        assert current.status_code == 201, current.text

    async def test_freeform_entries_unlimited_same_day(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        for i in range(3):
            response = await authenticated_async_client.post(
                f"{GAME}/diary", json={"kind": "freeform", "freeform": f"note {i}"}
            )
            assert response.status_code == 201, response.text
            assert response.json()["kind"] == "freeform"

    async def test_freeform_does_not_block_standup(
        self, authenticated_async_client: AsyncClient
    ) -> None:
        free = await authenticated_async_client.post(
            f"{GAME}/diary", json={"kind": "freeform", "freeform": "random thought"}
        )
        assert free.status_code == 201, free.text
        standup = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "a"})
        assert standup.status_code == 201, standup.text

    async def test_empty_entry_rejected(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.post(f"{GAME}/diary", json={})
        assert response.status_code == 422

    async def test_blank_fields_rejected(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "   "})
        assert response.status_code == 422

    async def test_create_requires_auth(self, async_client: AsyncClient) -> None:
        response = await async_client.post(f"{GAME}/diary", json={"good": "a"})
        assert response.status_code == 401


class TestDiaryReadUpdateDelete:
    async def test_get_entry(self, authenticated_async_client: AsyncClient) -> None:
        created = await authenticated_async_client.post(
            f"{GAME}/diary", json={"good": "a", "bad": "b"}
        )
        entry_id = created.json()["id"]

        response = await authenticated_async_client.get(f"{GAME}/diary/{entry_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == entry_id
        assert body["good"] == "a"
        assert body["bad"] == "b"

    async def test_get_missing_entry_404(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.get(f"{GAME}/diary/999999")
        assert response.status_code == 404

    async def test_patch_updates_fields(self, authenticated_async_client: AsyncClient) -> None:
        created = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "a"})
        entry_id = created.json()["id"]

        response = await authenticated_async_client.patch(
            f"{GAME}/diary/{entry_id}", json={"good": "better", "next": "sleep"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["good"] == "better"
        assert body["next"] == "sleep"

        fetched = await authenticated_async_client.get(f"{GAME}/diary/{entry_id}")
        assert fetched.json()["good"] == "better"

    async def test_patch_empty_body_400(self, authenticated_async_client: AsyncClient) -> None:
        created = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "a"})
        response = await authenticated_async_client.patch(
            f"{GAME}/diary/{created.json()['id']}", json={}
        )
        assert response.status_code == 400

    async def test_delete_entry(self, authenticated_async_client: AsyncClient) -> None:
        created = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "a"})
        entry_id = created.json()["id"]

        response = await authenticated_async_client.delete(f"{GAME}/diary/{entry_id}")
        assert response.status_code == 200, response.text

        fetched = await authenticated_async_client.get(f"{GAME}/diary/{entry_id}")
        assert fetched.status_code == 404

    async def test_list_entries_for_day(self, authenticated_async_client: AsyncClient) -> None:
        yesterday = (today() - timedelta(days=1)).isoformat()
        await authenticated_async_client.post(f"{GAME}/diary", json={"good": "today"})
        await authenticated_async_client.post(
            f"{GAME}/diary", json={"kind": "freeform", "freeform": "today note"}
        )
        await authenticated_async_client.post(
            f"{GAME}/diary", json={"entry_date": yesterday, "good": "yesterday"}
        )

        todays = await authenticated_async_client.get(f"{GAME}/diary", params={"date": today()})
        assert todays.status_code == 200, todays.text
        entries = todays.json()["entries"]
        assert len(entries) == 2
        assert all(e["entry_date"] == today().isoformat() for e in entries)

        all_entries = await authenticated_async_client.get(f"{GAME}/diary")
        assert len(all_entries.json()["entries"]) == 3

    async def test_entries_scoped_to_owner(
        self,
        authenticated_async_client: AsyncClient,
        async_client: AsyncClient,
        db: AsyncSession,
    ) -> None:
        created = await authenticated_async_client.post(f"{GAME}/diary", json={"good": "mine"})
        entry_id = created.json()["id"]

        other = await second_user_headers(async_client, db)
        headers = other["headers"]

        # Other user: no read, update, delete, or list visibility.
        assert (
            await async_client.get(f"{GAME}/diary/{entry_id}", headers=headers)
        ).status_code == 404
        assert (
            await async_client.patch(
                f"{GAME}/diary/{entry_id}", headers=headers, json={"good": "x"}
            )
        ).status_code == 404
        assert (
            await async_client.delete(f"{GAME}/diary/{entry_id}", headers=headers)
        ).status_code == 404
        listing = await async_client.get(f"{GAME}/diary", headers=headers)
        assert listing.json()["entries"] == []


class TestRetention:
    async def test_patch_retention(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "90d"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["retention"] == "90d"

        profile = await authenticated_async_client.get(f"{GAME}/profile")
        assert profile.json()["retention"] == "90d"

    async def test_retention_invalid_value(self, authenticated_async_client: AsyncClient) -> None:
        response = await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "30d"}
        )
        assert response.status_code == 422

    async def test_90d_hides_entries_older_than_90_days(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "90d"}
        )
        old = DiaryEntry(
            user_id=confirmed_user["id"],
            entry_date=today() - timedelta(days=100),
            kind="standup",
            good="ancient",
        )
        fresh = DiaryEntry(
            user_id=confirmed_user["id"],
            entry_date=today() - timedelta(days=10),
            kind="standup",
            good="recent",
        )
        db.add_all([old, fresh])
        await db.commit()

        listing = await authenticated_async_client.get(f"{GAME}/diary")
        dates = {e["entry_date"] for e in listing.json()["entries"]}
        assert fresh.entry_date.isoformat() in dates
        assert old.entry_date.isoformat() not in dates

        # Old entries are invisible to single reads and day queries too.
        assert (await authenticated_async_client.get(f"{GAME}/diary/{old.id}")).status_code == 404
        old_day = await authenticated_async_client.get(
            f"{GAME}/diary", params={"date": old.entry_date}
        )
        assert old_day.json()["entries"] == []

    async def test_forever_shows_everything(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "90d"}
        )
        await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "forever"}
        )
        old = DiaryEntry(
            user_id=confirmed_user["id"],
            entry_date=today() - timedelta(days=400),
            kind="standup",
            good="ancient",
        )
        db.add(old)
        await db.commit()

        listing = await authenticated_async_client.get(
            f"{GAME}/diary", params={"date": old.entry_date}
        )
        assert len(listing.json()["entries"]) == 1

    async def test_1y_cutoff(
        self,
        authenticated_async_client: AsyncClient,
        confirmed_user: dict,
        db: AsyncSession,
    ) -> None:
        await authenticated_async_client.patch(
            f"{GAME}/profile/retention", json={"retention": "1y"}
        )
        within = DiaryEntry(
            user_id=confirmed_user["id"],
            entry_date=today() - timedelta(days=200),
            kind="standup",
            good="within",
        )
        beyond = DiaryEntry(
            user_id=confirmed_user["id"],
            entry_date=today() - timedelta(days=400),
            kind="standup",
            good="beyond",
        )
        db.add_all([within, beyond])
        await db.commit()

        listing = await authenticated_async_client.get(f"{GAME}/diary")
        dates = {e["entry_date"] for e in listing.json()["entries"]}
        assert within.entry_date.isoformat() in dates
        assert beyond.entry_date.isoformat() not in dates
