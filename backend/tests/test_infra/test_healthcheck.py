"""The container's health probe.

Worth testing precisely because nothing else exercises it: a probe that answers wrongly either
reports a broken container as healthy, or restart-loops a working one.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lifeline import healthcheck


class Handler(BaseHTTPRequestHandler):
    """Answers with whatever the current test set."""

    status = 200
    body: bytes = json.dumps({"status": "ok", "database": "connected"}).encode()

    def do_GET(self) -> None:  # noqa: N802 - the name BaseHTTPRequestHandler dispatches to
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *_: object) -> None:
        """Keep the test output readable."""


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[Handler]]:
    """A stand-in API, with the probe pointed at it."""
    Handler.status = 200
    Handler.body = json.dumps({"status": "ok", "database": "connected"}).encode()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(healthcheck, "URL", f"http://127.0.0.1:{server.server_port}/api/health")
    try:
        yield Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestHealthcheck:
    def test_reports_healthy_when_the_api_answers(self, api: type[Handler]) -> None:
        assert healthcheck.main() == 0

    def test_reports_unhealthy_on_an_error_status(self, api: type[Handler]) -> None:
        api.status = 503

        assert healthcheck.main() == 1

    def test_reports_unhealthy_on_a_success_that_is_not_200(self, api: type[Handler]) -> None:
        # urlopen raises for 4xx and 5xx, so this is the only way into that branch — and a 204
        # is not an answer to a health question either.
        api.status = 204

        assert healthcheck.main() == 1

    def test_reports_unhealthy_when_the_database_is_unreachable(self, api: type[Handler]) -> None:
        # The container is serving, but every request it serves fails. A probe that only
        # checked the port would call this healthy.
        api.body = json.dumps({"status": "degraded", "database": "unavailable"}).encode()

        assert healthcheck.main() == 1

    def test_reports_unhealthy_on_a_response_that_is_not_json(self, api: type[Handler]) -> None:
        api.body = b"<html>gateway error</html>"

        assert healthcheck.main() == 1

    def test_reports_unhealthy_when_nothing_is_listening(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        monkeypatch.setattr(healthcheck, "URL", f"http://127.0.0.1:{port}/api/health")

        assert healthcheck.main() == 1
