"""Relaying the VNC protocol between a websocket and a TCP socket."""

import asyncio

import pytest

from lifeline.services.browser.bridge import pump


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


async def echo_server() -> tuple[asyncio.Server, int]:
    """A TCP server standing in for x11vnc."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while data := await reader.read(1024):
                writer.write(b"echo:" + data)
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


class TestPump:
    async def test_carries_bytes_in_both_directions(self) -> None:
        server, port = await echo_server()
        websocket = FakeWebSocket(b"RFB 003.008\n")
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        task = asyncio.create_task(pump(websocket, reader, writer))
        try:
            for _ in range(100):
                if websocket.sent:
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()

        assert websocket.sent == [b"echo:RFB 003.008\n"]

    async def test_returns_when_the_vnc_server_closes(self) -> None:
        # The browser was closed, so the stream has nothing left to carry.
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        try:
            await asyncio.wait_for(pump(FakeWebSocket(), reader, writer), timeout=5)
        finally:
            server.close()
            await server.wait_closed()

    async def test_surfaces_a_failure_on_the_client_side(self) -> None:
        server, port = await echo_server()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        class BrokenWebSocket(FakeWebSocket):
            async def receive_bytes(self) -> bytes:
                raise RuntimeError("the tab went away")

        try:
            with pytest.raises(RuntimeError, match="the tab went away"):
                await asyncio.wait_for(pump(BrokenWebSocket(), reader, writer), timeout=5)
        finally:
            server.close()
            await server.wait_closed()

    async def test_closes_the_tcp_connection_on_the_way_out(self) -> None:
        # Left open, every abandoned login stream would hold a socket against x11vnc.
        server, port = await echo_server()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        class BrokenWebSocket(FakeWebSocket):
            async def receive_bytes(self) -> bytes:
                raise RuntimeError("gone")

        try:
            with pytest.raises(RuntimeError):
                await pump(BrokenWebSocket(), reader, writer)
        finally:
            server.close()
            await server.wait_closed()

        assert writer.is_closing()
