"""Opening, streaming, saving and abandoning an interactive login."""

import asyncio
import socket

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lifeline.models import Site, User
from tests.conftest import SAMPLE_STATE, EchoServer


@pytest.fixture
async def created(logged_in: httpx.AsyncClient) -> dict:
    response = await logged_in.post(
        "/api/sites",
        json={
            "name": "example",
            "ping_url": "https://example.org/home",
            "login_url": "https://example.org/login.php",
        },
    )
    return response.json()


class TestOpening:
    async def test_starts_a_session_at_the_login_url(
        self, logged_in: httpx.AsyncClient, created: dict, fake_driver
    ) -> None:
        response = await logged_in.post(f"/api/sites/{created['id']}/login-session")

        assert response.status_code == 200
        body = response.json()
        assert body["ws_path"].startswith("/api/browser/")
        assert body["width"] > 0
        assert fake_driver.opened[0][2] == "https://example.org/login.php"

    async def test_falls_back_to_the_ping_url_when_no_login_url_is_set(
        self, logged_in: httpx.AsyncClient, fake_driver
    ) -> None:
        created = (
            await logged_in.post(
                "/api/sites", json={"name": "bare", "ping_url": "https://example.org/home"}
            )
        ).json()

        await logged_in.post(f"/api/sites/{created['id']}/login-session")

        assert fake_driver.opened[0][2] == "https://example.org/home"

    async def test_reports_a_deployment_without_a_browser(
        self, logged_in: httpx.AsyncClient, created: dict, services
    ) -> None:
        services.settings.browser_enabled = False

        response = await logged_in.post(f"/api/sites/{created['id']}/login-session")

        assert response.status_code == 503

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.post("/api/sites/404/login-session")).status_code == 404

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.post("/api/sites/1/login-session")).status_code == 401


class TestSaving:
    async def test_stores_the_session_from_the_live_browser(
        self, logged_in: httpx.AsyncClient, created: dict, db: AsyncSession, cipher
    ) -> None:
        opened = (await logged_in.post(f"/api/sites/{created['id']}/login-session")).json()
        token = opened["ws_path"].split("/")[3]

        response = await logged_in.post(f"/api/browser/{token}/save")

        assert response.status_code == 200
        db.expunge_all()
        site = await db.get(Site, created["id"])
        assert cipher.decrypt_json(site.session.state) == SAMPLE_STATE
        assert site.session.captured_via == "browser"
        # Captured with the session, because a clearance cookie is bound to the agent that
        # earned it.
        assert site.user_agent == "FakeAgent/1"

    async def test_closes_the_browser_once_it_is_saved(
        self, logged_in: httpx.AsyncClient, created: dict, services, fake_processes
    ) -> None:
        opened = (await logged_in.post(f"/api/sites/{created['id']}/login-session")).json()
        token = opened["ws_path"].split("/")[3]

        await logged_in.post(f"/api/browser/{token}/save")

        assert services.browser.active is None
        assert fake_processes.running == []

    async def test_rejects_an_unknown_token(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.post("/api/browser/not-a-token/save")).status_code == 404

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.post("/api/browser/whatever/save")).status_code == 401


class TestAbandoning:
    async def test_closes_without_saving(
        self, logged_in: httpx.AsyncClient, created: dict, db: AsyncSession, services
    ) -> None:
        opened = (await logged_in.post(f"/api/sites/{created['id']}/login-session")).json()
        token = opened["ws_path"].split("/")[3]

        response = await logged_in.delete(f"/api/browser/{token}")

        assert response.status_code == 200
        assert services.browser.active is None
        db.expunge_all()
        assert (await db.get(Site, created["id"])).session is None

    async def test_rejects_an_unknown_token(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.delete("/api/browser/not-a-token")).status_code == 404


class AsgiWebSocket:
    """Drives an ASGI websocket route directly.

    Written out rather than using Starlette's test client, which now wants a second HTTP
    library installed alongside the one the application uses. Talking ASGI is a dozen
    messages, and it keeps the route, the bridge and the fake VNC server in one event loop.
    """

    def __init__(self, app: object, path: str, subprotocols: list[str] | None = None) -> None:
        self._app = app
        self._path = path
        # Empty by default, because that is what noVNC sends. Offering what the server happens
        # to want would make this test agree with the code rather than with the real client.
        self._subprotocols = subprotocols if subprotocols is not None else []
        self._to_app: asyncio.Queue[dict] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.accepted = False
        self.close_message: dict | None = None

    async def __aenter__(self) -> AsgiWebSocket:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"lifeline.test")],
            "client": ("127.0.0.1", 12345),
            "server": ("lifeline.test", 80),
            "subprotocols": self._subprotocols,
            # The route reads websocket.app.state to reach the services.
            "app": self._app,
        }
        self._task = asyncio.create_task(self._app(scope, self._to_app.get, self._from_app.put))
        await self._to_app.put({"type": "websocket.connect"})
        first = await asyncio.wait_for(self._from_app.get(), timeout=5)
        self.accepted = first["type"] == "websocket.accept"
        self.subprotocol = first.get("subprotocol")
        if not self.accepted:
            self.close_message = first
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def send_bytes(self, data: bytes) -> None:
        await self._to_app.put({"type": "websocket.receive", "bytes": data})

    async def receive_bytes(self) -> bytes:
        message = await asyncio.wait_for(self._from_app.get(), timeout=5)
        assert message["type"] == "websocket.send", message
        return message["bytes"]


def unused_port() -> int:
    """A port with nothing listening on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def install_session(services, rfb_port: int):
    """Put a login session in place, pointing at a given RFB port.

    Built directly rather than through open_login: these tests are about the streaming route,
    and the manager's own tests cover how a session comes to exist.
    """
    from datetime import UTC, datetime, timedelta

    from lifeline.services.browser.manager import LoginSession
    from tests.conftest import FakeBrowser

    now = datetime.now(UTC)
    session = LoginSession(
        site_id=1,
        token="test-stream-token",
        display=":99",
        rfb_port=rfb_port,
        browser=FakeBrowser(),
        processes=[],
        profile_dir=services.settings.profiles_dir / "1",
        idle_timeout=timedelta(minutes=15),
        expires_at=now + timedelta(minutes=15),
        hard_deadline=now + timedelta(hours=4),
    )
    services.browser._active = session
    return session


class TestStream:
    GREETING = b"RFB 003.008\n"

    async def test_carries_the_vnc_protocol_both_ways(self, app, services) -> None:
        async with EchoServer(greeting=self.GREETING) as vnc:
            session = install_session(services, vnc.port)

            async with AsgiWebSocket(app, f"/api/browser/{session.token}/ws") as websocket:
                assert websocket.accepted is True
                assert await websocket.receive_bytes() == self.GREETING

                await websocket.send_bytes(b"hello")

                assert await websocket.receive_bytes() == b"echo:hello"

    async def test_names_no_subprotocol_when_the_client_offered_none(self, app, services) -> None:
        # What noVNC does. A server that answers with one the client never offered makes the
        # browser fail the connection, and the login panel shows the stream dropping at once.
        async with EchoServer(greeting=self.GREETING) as vnc:
            session = install_session(services, vnc.port)

            async with AsgiWebSocket(app, f"/api/browser/{session.token}/ws") as websocket:
                assert websocket.accepted is True
                assert websocket.subprotocol is None
                # Read before leaving, so the stream is proven to work and not merely to have
                # been accepted — and so the server has certainly seen the connection.
                assert await websocket.receive_bytes() == self.GREETING

    async def test_echoes_the_subprotocol_when_one_is_offered(self, app, services) -> None:
        async with EchoServer(greeting=self.GREETING) as vnc:
            session = install_session(services, vnc.port)

            async with AsgiWebSocket(
                app, f"/api/browser/{session.token}/ws", subprotocols=["binary"]
            ) as websocket:
                assert websocket.subprotocol == "binary"
                assert await websocket.receive_bytes() == self.GREETING

    async def test_counts_the_viewer_while_it_is_connected(self, app, services) -> None:
        # A tab watching the stream is a session in use, which the idle timeout must respect.
        async with EchoServer(greeting=self.GREETING) as vnc:
            session = install_session(services, vnc.port)

            async with AsgiWebSocket(app, f"/api/browser/{session.token}/ws") as websocket:
                await websocket.receive_bytes()

                assert session.viewers == 1

    async def test_refuses_an_unknown_token(self, app, services) -> None:
        # The token is what stands between the internet and a logged-in browser.
        async with AsgiWebSocket(app, "/api/browser/not-a-token/ws") as websocket:
            assert websocket.accepted is False
            assert websocket.close_message["code"] == 1008

    async def test_reports_a_vnc_server_that_cannot_be_reached(self, app, services) -> None:
        # The session's X server died under it.
        session = install_session(services, unused_port())

        async with AsgiWebSocket(app, f"/api/browser/{session.token}/ws") as websocket:
            assert websocket.accepted is True
            message = await asyncio.wait_for(websocket._from_app.get(), timeout=5)
            assert message["type"] == "websocket.close"
            assert message["code"] == 1011
