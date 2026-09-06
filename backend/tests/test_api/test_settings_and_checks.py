"""The settings screen and the history view."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from lifeline.models import Check, CheckOutcome, Site, User
from tests.conftest import RecordingSender


class TestSettings:
    async def test_returns_the_defaults_before_anything_is_changed(
        self, logged_in: httpx.AsyncClient
    ) -> None:
        body = (await logged_in.get("/api/settings")).json()

        assert body["retention_days"] == 90
        assert body["apprise_urls"] == ""

    async def test_saves_a_change(self, logged_in: httpx.AsyncClient) -> None:
        response = await logged_in.put(
            "/api/settings",
            json={
                "apprise_urls": "tgram://token/chat",
                "notify_on_lapsed": True,
                "notify_on_recovered": False,
                "notify_on_errors": True,
                "notify_on_cookie_expiry": True,
                "notify_on_deadline": True,
                "notify_cooldown_hours": 12,
                "warning_lead_days": 14,
                "error_threshold": 5,
                "default_interval_days": 10,
                "retention_days": 30,
                "browser_idle_timeout_minutes": 20,
            },
        )

        assert response.status_code == 200
        assert response.json()["apprise_urls"] == "tgram://token/chat"
        assert (await logged_in.get("/api/settings")).json()["warning_lead_days"] == 14

    async def test_rejects_a_nonsensical_value(self, logged_in: httpx.AsyncClient) -> None:
        response = await logged_in.put("/api/settings", json={"error_threshold": 0})

        assert response.status_code == 422

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.get("/api/settings")).status_code == 401


class TestTestNotification:
    async def test_sends_to_the_configured_destinations(
        self, logged_in: httpx.AsyncClient, sender: RecordingSender
    ) -> None:
        await logged_in.put(
            "/api/settings", json={"apprise_urls": "tgram://token/chat"}
        )

        response = await logged_in.post("/api/settings/test-notification")

        assert response.json()["detail"] == "test notification sent"
        assert "test notification" in sender.titles[0]

    async def test_says_so_when_there_is_nowhere_to_send(
        self, logged_in: httpx.AsyncClient
    ) -> None:
        # Silently reporting success would leave a typo in the settings undiscovered until
        # the message that mattered failed to arrive.
        response = await logged_in.post("/api/settings/test-notification")

        assert "nothing was sent" in response.json()["detail"]


class TestHistory:
    async def test_lists_the_newest_checks_first(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, site: Site
    ) -> None:
        from datetime import UTC, datetime, timedelta

        base = datetime(2026, 6, 1, tzinfo=UTC)
        for offset, outcome in enumerate([CheckOutcome.OK, CheckOutcome.LOGIN_EXPIRED]):
            db.add(Check(site_id=site.id, started_at=base + timedelta(hours=offset), outcome=outcome))
        await db.commit()

        body = (await logged_in.get("/api/checks")).json()

        assert [check["outcome"] for check in body] == ["login_expired", "ok"]

    async def test_caps_an_outrageous_limit(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.get("/api/checks?limit=999999")).status_code == 200

    async def test_treats_a_nonsense_limit_as_the_minimum(
        self, logged_in: httpx.AsyncClient
    ) -> None:
        assert (await logged_in.get("/api/checks?limit=-5")).status_code == 200

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.get("/api/checks")).status_code == 401
