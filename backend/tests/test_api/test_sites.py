"""Managing sites over HTTP."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lifeline.models import CaptureMethod, Site, SiteSession, SiteStatus, User

NEW_SITE = {
    "name": "example",
    "ping_url": "https://example.org/home",
    "login_url": "https://example.org/login.php",
    "interval_days": 14,
    "inactivity_limit_days": 90,
    "login_url_pattern": "login.php",
    "success_pattern": "Logged in as",
}


@pytest.fixture
async def created(logged_in: httpx.AsyncClient) -> dict:
    """One site, created through the API."""
    response = await logged_in.post("/api/sites", json=NEW_SITE)
    assert response.status_code == 201
    return response.json()


class TestCreate:
    async def test_stores_what_was_sent(self, created: dict) -> None:
        assert created["name"] == "example"
        assert created["interval_days"] == 14
        assert created["inactivity_limit_days"] == 90
        assert created["status"] == SiteStatus.UNKNOWN
        assert created["session"] is None

    async def test_a_new_site_has_an_empty_pulse(self, created: dict) -> None:
        assert created["pulse"] == []

    async def test_rejects_a_duplicate_name(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        assert (await logged_in.post("/api/sites", json=NEW_SITE)).status_code == 409

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "data:text/html,x", "ftp://host/x"])
    async def test_rejects_a_url_that_is_not_http(
        self, logged_in: httpx.AsyncClient, url: str
    ) -> None:
        # The ping is made with the site's cookies; a file:// target would be a way to make
        # the server read something it should not.
        response = await logged_in.post("/api/sites", json={**NEW_SITE, "ping_url": url})

        assert response.status_code == 422

    async def test_rejects_an_interval_of_zero(self, logged_in: httpx.AsyncClient) -> None:
        response = await logged_in.post("/api/sites", json={**NEW_SITE, "interval_days": 0})

        assert response.status_code == 422

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.post("/api/sites", json=NEW_SITE)).status_code == 401


class TestRead:
    async def test_lists_sites(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        response = await logged_in.get("/api/sites")

        assert [site["name"] for site in response.json()] == ["example"]

    async def test_shows_one_site(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        assert (await logged_in.get(f"/api/sites/{created['id']}")).json()["name"] == "example"

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.get("/api/sites/404")).status_code == 404

    async def test_never_returns_the_stored_session_itself(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict
    ) -> None:
        # The session is equivalent to being logged in; it must not leave the server.
        site = await db.get(Site, created["id"])
        site.session = SiteSession(
            state=cipher.encrypt_json({"cookies": [], "origins": []}),
            captured_via=CaptureMethod.IMPORT,
            captured_at=site.created_at,
            cookie_names="session,uid",
        )
        await db.commit()

        body = (await logged_in.get(f"/api/sites/{created['id']}")).json()

        assert body["session"]["cookie_names"] == ["session", "uid"]
        assert "state" not in body["session"]


class TestUpdate:
    async def test_changes_a_field(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        response = await logged_in.put(
            f"/api/sites/{created['id']}", json={**NEW_SITE, "interval_days": 30}
        )

        assert response.json()["interval_days"] == 30

    async def test_can_rename_a_site(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        response = await logged_in.put(
            f"/api/sites/{created['id']}", json={**NEW_SITE, "name": "renamed"}
        )

        assert response.json()["name"] == "renamed"

    async def test_rejects_renaming_onto_another_site(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post("/api/sites", json={**NEW_SITE, "name": "other"})

        response = await logged_in.put(
            f"/api/sites/{created['id']}", json={**NEW_SITE, "name": "other"}
        )

        assert response.status_code == 409

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.put("/api/sites/404", json=NEW_SITE)).status_code == 404


class TestDelete:
    async def test_removes_the_site(
        self, logged_in: httpx.AsyncClient, created: dict, db: AsyncSession
    ) -> None:
        response = await logged_in.delete(f"/api/sites/{created['id']}")

        assert response.status_code == 204
        db.expunge_all()
        assert (await db.execute(select(Site))).scalars().all() == []

    async def test_removes_the_browser_profile_too(
        self, logged_in: httpx.AsyncClient, created: dict, services
    ) -> None:
        # The profile holds cookies; leaving it behind would keep the session on disk after
        # the site was apparently deleted.
        profile = services.browser.profile_dir(created["id"])
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "Cookies").write_text("secrets")

        await logged_in.delete(f"/api/sites/{created['id']}")

        assert not profile.exists()

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.delete("/api/sites/404")).status_code == 404


class TestCheckNow:
    async def test_runs_a_check_and_returns_it(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.post(f"/api/sites/{created['id']}/check")

        assert response.status_code == 200
        # No session has been captured, so the honest answer is that a login is needed.
        assert response.json()["outcome"] == "login_expired"

    async def test_appears_in_the_history(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(f"/api/sites/{created['id']}/check")

        history = (await logged_in.get(f"/api/sites/{created['id']}/checks")).json()

        assert len(history) == 1

    async def test_shows_up_in_the_pulse(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(f"/api/sites/{created['id']}/check")

        listed = (await logged_in.get("/api/sites")).json()[0]

        assert listed["pulse"] == ["login_expired"]

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.post("/api/sites/404/check")).status_code == 404


class TestSessionImport:
    async def test_stores_a_pasted_cookie_header(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.post(
            f"/api/sites/{created['id']}/session/import",
            json={"text": "uid=1234; pass=abcdef", "user_agent": "Pasted/1.0"},
        )

        assert response.status_code == 200
        site = (await logged_in.get(f"/api/sites/{created['id']}")).json()
        assert site["session"]["cookie_names"] == ["pass", "uid"]
        assert site["session"]["captured_via"] == "import"
        assert site["user_agent"] == "Pasted/1.0"

    async def test_rejects_text_that_is_not_cookies(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.post(
            f"/api/sites/{created['id']}/session/import", json={"text": "just some prose"}
        )

        assert response.status_code == 422
        assert "name=value" in response.json()["detail"]

    async def test_a_check_after_importing_uses_the_session(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(
            f"/api/sites/{created['id']}/session/import", json={"text": "uid=1234"}
        )

        outcome = (await logged_in.post(f"/api/sites/{created['id']}/check")).json()

        assert outcome["outcome"] == "ok"

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        response = await logged_in.post("/api/sites/404/session/import", json={"text": "a=b"})

        assert response.status_code == 404


class TestSessionRemoval:
    async def test_discards_the_stored_session(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(
            f"/api/sites/{created['id']}/session/import", json={"text": "uid=1234"}
        )

        response = await logged_in.delete(f"/api/sites/{created['id']}/session")

        assert response.status_code == 200
        assert (await logged_in.get(f"/api/sites/{created['id']}")).json()["session"] is None

    async def test_is_harmless_when_there_is_no_session(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        assert (await logged_in.delete(f"/api/sites/{created['id']}/session")).status_code == 200


class TestHistory:
    async def test_caps_an_outrageous_limit(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.get(f"/api/sites/{created['id']}/checks?limit=100000")

        assert response.status_code == 200

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.get("/api/sites/404/checks")).status_code == 404
