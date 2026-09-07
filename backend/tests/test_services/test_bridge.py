"""Relaying the VNC protocol between a websocket and a TCP socket."""

import asyncio

import pytest

from lifeline.services.browser.bridge import pump
from tests.conftest import EchoServer


class BrokenWebSocket:
    """A client that fails the moment it is read from."""

    def __init__(self, message: str) -> None:
        self._message = message
        self.sent: list[bytes] = []

    async def receive_bytes(self) -> bytes:
        raise RuntimeError(self._message)

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)


class FakeWebSocket:
    """A websocket that yields queued frames and records what is sent back."""

    def __init__(self, *incoming: bytes, then: Exception | None = None) -> None:
        self._incoming = list(incoming)
        self._then = then or asyncio.CancelledError()
        self.sent: list[bytes] = []
        self.receive_waits = asyncio.Event()

    async def receive_bytes(self) -> bytes:
        if self._incoming:
            return self._incoming.pop(0)
        self.receive_waits.set()
        # Nothing more is coming; block the way a quiet client does rather than reporting a
        # close that did not happen.
        await asyncio.sleep(3600)
        raise self._then

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)


class TestPump:
    async def test_carries_bytes_in_both_directions(self) -> None:
        async with EchoServer() as vnc:
            websocket = FakeWebSocket(b"RFB 003.008\n")
            reader, writer = await asyncio.open_connection("127.0.0.1", vnc.port)
            task = asyncio.create_task(pump(websocket, reader, writer))
            try:
                for _ in range(200):
                    if websocket.sent:
                        break
                    await asyncio.sleep(0.01)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        assert websocket.sent == [b"echo:RFB 003.008\n"]

    async def test_returns_when_the_vnc_server_closes(self) -> None:
        # The browser was closed, so the stream has nothing left to carry.
        async with EchoServer(hang_up=True) as vnc:
            reader, writer = await asyncio.open_connection("127.0.0.1", vnc.port)

            await asyncio.wait_for(pump(FakeWebSocket(), reader, writer), timeout=5)

    async def test_surfaces_a_failure_on_the_client_side(self) -> None:
        async with EchoServer() as vnc:
            reader, writer = await asyncio.open_connection("127.0.0.1", vnc.port)

            with pytest.raises(RuntimeError, match="the tab went away"):
                await asyncio.wait_for(
                    pump(BrokenWebSocket("the tab went away"), reader, writer), timeout=5
                )

    async def test_closes_the_tcp_connection_on_the_way_out(self) -> None:
        # Left open, every abandoned login stream would hold a socket against x11vnc.
        async with EchoServer() as vnc:
            reader, writer = await asyncio.open_connection("127.0.0.1", vnc.port)

            with pytest.raises(RuntimeError):
                await pump(BrokenWebSocket("gone"), reader, writer)

        assert writer.is_closing()
