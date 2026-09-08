"""The first-run wizard, logging in, and what is refused before either has happened."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lifeline.api.deps import SETUP_REQUIRED_DETAIL
from lifeline.config import SETUP_TOKEN_DISABLED
from lifeline.models import Setting, User

GOOD_PASSWORD = "a-good-long-password"


class TestHealth:
    async def test_reports_the_database_as_reachable(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["database"] == "connected"

    async def test_needs_no_setup_or_login(self, client: httpx.AsyncClient) -> None:
        # The container's health probe runs before anyone has configured the instance.
        assert (await client.get("/api/health")).status_code == 200


class TestSetupState:
    async def test_reports_that_setup_is_needed(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/setup")

        assert response.json() == {"setup_required": True, "token_required": True}

    async def test_reports_when_setup_is_done(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.get("/api/setup")).json()["setup_required"] is False

    async def test_reports_an_unguarded_wizard(self, client: httpx.AsyncClient, app) -> None:
        app.state.setup_token = None

        assert (await client.get("/api/setup")).json()["token_required"] is False

    async def test_refuses_setup_when_the_guard_went_missing(
        self, client: httpx.AsyncClient, app
    ) -> None:
        # No token was minted because there was an administrator at boot, and now there is none:
        # something emptied the user table, and the wizard must not be claimable by whoever asks.
        app.state.setup_token = None

        response = await client.post(
            "/api/setup", json={"username": "someone", "password": "a-long-enough-password"}
        )

        assert response.status_code == 403
        assert "restart" in response.json()["detail"]


class TestSetupCompletion:
    async def test_creates_the_administrator_and_logs_in(
        self, client: httpx.AsyncClient, db: AsyncSession, services
    ) -> None:
        response = await client.post(
            "/api/setup",
            json={
                "username": "jure",
                "password": GOOD_PASSWORD,
                "token": services.settings.setup_token,
            },
        )

        assert response.status_code == 201
        assert response.json()["username"] == "jure"
        assert services.settings.session_cookie_name in response.cookies
        assert (await db.execute(select(User))).scalar_one().username == "jure"

    async def test_creates_the_settings_row(
        self, client: httpx.AsyncClient, db: AsyncSession, services
    ) -> None:
        # So every later request can rely on it existing.
        await client.post(
            "/api/setup",
            json={
                "username": "jure",
                "password": GOOD_PASSWORD,
                "token": services.settings.setup_token,
            },
        )

        assert (await db.execute(select(Setting))).scalar_one() is not None

    async def test_refuses_the_wrong_token(self, client: httpx.AsyncClient) -> None:
        # This instance may be reachable from the internet before anyone configures it.
        response = await client.post(
            "/api/setup",
            json={"username": "someone", "password": GOOD_PASSWORD, "token": "guessed"},
        )

        assert response.status_code == 403

    async def test_refuses_a_missing_token(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/setup", json={"username": "someone", "password": GOOD_PASSWORD}
        )

        assert response.status_code == 403

    async def test_accepts_no_token_when_the_guard_is_off(
        self, client: httpx.AsyncClient, app, services
    ) -> None:
        # Both halves of the real configuration: nothing was minted *because* the guard is off.
        # Blanking the token alone would instead look like a wizard that lost its guard.
        services.settings.setup_token = SETUP_TOKEN_DISABLED
        app.state.setup_token = None

        response = await client.post(
            "/api/setup", json={"username": "jure", "password": GOOD_PASSWORD}
        )

        assert response.status_code == 201

    async def test_refuses_a_short_password(
        self, client: httpx.AsyncClient, services
    ) -> None:
        response = await client.post(
            "/api/setup",
            json={"username": "jure", "password": "short", "token": services.settings.setup_token},
        )

        assert response.status_code == 422
        assert "at least" in response.json()["detail"]

    async def test_cannot_be_run_twice(
        self, client: httpx.AsyncClient, admin: User, services
    ) -> None:
        response = await client.post(
            "/api/setup",
            json={
                "username": "someone-else",
                "password": GOOD_PASSWORD,
                "token": services.settings.setup_token,
            },
        )

        assert response.status_code == 409

    async def test_the_token_is_spent_once_setup_completes(
        self, client: httpx.AsyncClient, app, services
    ) -> None:
        await client.post(
            "/api/setup",
            json={
                "username": "jure",
                "password": GOOD_PASSWORD,
                "token": services.settings.setup_token,
            },
        )

        assert app.state.setup_token is None


class TestSetupGuard:
    @pytest.mark.parametrize("path", ["/api/sites", "/api/settings", "/api/checks"])
    async def test_ordinary_endpoints_report_that_setup_is_needed(
        self, client: httpx.AsyncClient, path: str
    ) -> None:
        # Distinct from a 401 so the UI shows the wizard rather than a login form nobody can
        # get past.
        response = await client.get(path)

        assert response.status_code == 409
        assert response.json()["detail"] == SETUP_REQUIRED_DETAIL


class TestLogin:
    async def test_accepts_the_right_password(
        self, client: httpx.AsyncClient, admin: User, services
    ) -> None:
        response = await client.post(
            "/api/auth/login", json={"username": "jure", "password": GOOD_PASSWORD}
        )

        assert response.status_code == 200
        assert services.settings.session_cookie_name in response.cookies

    async def test_records_the_login_time(
        self, client: httpx.AsyncClient, admin: User, db: AsyncSession
    ) -> None:
        await client.post("/api/auth/login", json={"username": "jure", "password": GOOD_PASSWORD})

        db.expunge_all()
        assert (await db.get(User, admin.id)).last_login_at is not None

    async def test_rejects_the_wrong_password(
        self, client: httpx.AsyncClient, admin: User
    ) -> None:
        response = await client.post(
            "/api/auth/login", json={"username": "jure", "password": "not-the-password"}
        )

        assert response.status_code == 401

    async def test_says_the_same_thing_for_an_unknown_user(
        self, client: httpx.AsyncClient, admin: User
    ) -> None:
        # Distinguishing the two tells an unauthenticated caller which usernames exist.
        wrong_password = await client.post(
            "/api/auth/login", json={"username": "jure", "password": "wrong"}
        )
        unknown_user = await client.post(
            "/api/auth/login", json={"username": "nobody", "password": "wrong"}
        )

        assert wrong_password.json()["detail"] == unknown_user.json()["detail"]

    async def test_throttles_repeated_attempts(
        self, client: httpx.AsyncClient, admin: User, services
    ) -> None:
        for _ in range(services.settings.login_rate_limit_per_minute):
            await client.post("/api/auth/login", json={"username": "jure", "password": "wrong"})

        response = await client.post(
            "/api/auth/login", json={"username": "jure", "password": "wrong"}
        )

        assert response.status_code == 429

    async def test_a_successful_login_clears_the_throttle(
        self, client: httpx.AsyncClient, admin: User, services
    ) -> None:
        for _ in range(services.settings.login_rate_limit_per_minute - 1):
            await client.post("/api/auth/login", json={"username": "jure", "password": "wrong"})

        assert (
            await client.post(
                "/api/auth/login", json={"username": "jure", "password": GOOD_PASSWORD}
            )
        ).status_code == 200
        assert (
            await client.post(
                "/api/auth/login", json={"username": "jure", "password": GOOD_PASSWORD}
            )
        ).status_code == 200


class TestAuthorisation:
    async def test_refuses_a_request_with_no_cookie(
        self, client: httpx.AsyncClient, admin: User
    ) -> None:
        assert (await client.get("/api/sites")).status_code == 401

    async def test_refuses_a_tampered_cookie(
        self, client: httpx.AsyncClient, admin: User, services
    ) -> None:
        client.cookies.set(services.settings.session_cookie_name, "not-a-real-token")

        assert (await client.get("/api/sites")).status_code == 401

    async def test_refuses_a_cookie_whose_user_is_gone(
        self, client: httpx.AsyncClient, admin: User, services, db: AsyncSession
    ) -> None:
        client.cookies.set(
            services.settings.session_cookie_name, services.cookies.issue(admin.id + 99)
        )

        assert (await client.get("/api/sites")).status_code == 401

    async def test_accepts_a_valid_cookie(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.get("/api/sites")).status_code == 200

    async def test_logging_out_clears_the_cookie(self, logged_in: httpx.AsyncClient) -> None:
        response = await logged_in.post("/api/auth/logout")

        assert response.status_code == 200
        assert "sites" not in response.text

    async def test_reports_who_is_logged_in(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.get("/api/auth/me")).json()["username"] == "jure"

    async def test_the_cookie_is_marked_secure_behind_a_tls_proxy(
        self, client: httpx.AsyncClient, admin: User
    ) -> None:
        # The proxy terminates TLS, so the request arrives over plain HTTP; without reading
        # the forwarded scheme the cookie would go out without Secure.
        response = await client.post(
            "/api/auth/login",
            json={"username": "jure", "password": GOOD_PASSWORD},
            headers={"x-forwarded-proto": "https"},
        )

        assert "Secure" in response.headers["set-cookie"]

    async def test_the_cookie_is_not_secure_over_plain_http(
        self, client: httpx.AsyncClient, admin: User
    ) -> None:
        # A Secure cookie is discarded by the browser on a plain-HTTP instance, which looks
        # exactly like a rejected password.
        response = await client.post(
            "/api/auth/login", json={"username": "jure", "password": GOOD_PASSWORD}
        )

        assert "Secure" not in response.headers["set-cookie"]

    async def test_a_deployment_can_force_the_secure_flag(
        self, client: httpx.AsyncClient, admin: User, services
    ) -> None:
        services.settings.cookie_secure = True

        response = await client.post(
            "/api/auth/login", json={"username": "jure", "password": GOOD_PASSWORD}
        )

        assert "Secure" in response.headers["set-cookie"]

    async def test_authentication_can_be_disabled(
        self, client: httpx.AsyncClient, admin: User, services
    ) -> None:
        # For an instance already behind someone else's authentication.
        services.settings.auth_disabled = True

        assert (await client.get("/api/sites")).status_code == 200
        assert (await client.get("/api/auth/me")).json()["username"] == "anonymous"
