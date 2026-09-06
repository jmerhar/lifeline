"""Carrying the VNC protocol between a browser tab and the X server's VNC port.

noVNC speaks RFB over a WebSocket, and x11vnc speaks RFB over TCP. Pumping bytes between
the two here removes the websockify process that would otherwise sit in the middle — one
fewer thing to supervise, and one fewer thing to leak.
"""

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)

# Big enough for a full framebuffer update to move in few reads, small enough that a slow
# client cannot make this hold much memory.
CHUNK_BYTES = 65536


class WebSocketLike(Protocol):
    """The part of a WebSocket connection this needs."""

    async def receive_bytes(self) -> bytes: ...
    async def send_bytes(self, data: bytes) -> None: ...


async def pump(
    websocket: WebSocketLike,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Relay in both directions until either side closes.

    The two directions are separate tasks because RFB is fully asynchronous: the server
    pushes framebuffer updates while the client sends input, and reading one direction at a
    time would stall the pointer whenever the screen was quiet.
    """

    async def client_to_server() -> None:
        while True:
            data = await websocket.receive_bytes()
            writer.write(data)
            await writer.drain()

    async def server_to_client() -> None:
        while True:
            data = await reader.read(CHUNK_BYTES)
            if not data:
                return
            await websocket.send_bytes(data)

    tasks = [
        asyncio.create_task(client_to_server(), name="vnc-c2s"),
        asyncio.create_task(server_to_client(), name="vnc-s2c"),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        # Surfaces a genuine failure rather than letting the connection close silently, and
        # swallowing the cancellation of the other direction, which is expected.
        for task in done:
            if task.exception() is not None:
                raise task.exception()
    finally:
        # Both directions are cancelled and awaited before returning, so no task is left
        # writing to a closed transport after the handler has moved on.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            # The peer is already gone; there is nothing left to close cleanly.
            pass
