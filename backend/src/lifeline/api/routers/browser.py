"""Streaming a live login session, and saving what it earned.

Addressed by the session's token rather than by site: the token is minted when the session
is opened, is unguessable, and is only ever handed to a caller that had already
authenticated — which matters most for the websocket, where a browser will not act on an
HTTP authentication challenge.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from ...models import CaptureMethod
from ...schemas import Message
from ...services.browser.bridge import pump
from ...services.browser.manager import NoSuchLoginSession
from ..deps import DbDep, ServicesDep, require_setup_complete, require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/browser", tags=["browser"])
GUARDED = [Depends(require_setup_complete), Depends(require_user)]


@router.post("/{token}/save", dependencies=GUARDED)
async def save_session(token: str, db: DbDep, services: ServicesDep) -> Message:
    """Store the session the live browser is holding, then close it."""
    try:
        site_id = services.browser.get(token).site_id
        state, user_agent = await services.browser.capture(token)
    except NoSuchLoginSession as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="that login session is not open"
        ) from exc

    await db.commit()
    await services.runner.store_session(
        site_id, state, CaptureMethod.BROWSER, user_agent=user_agent
    )
    # Closed as soon as it is saved: a headful browser is the most expensive thing here, and
    # leaving one running costs the host for nothing.
    await services.browser.close()
    return Message(detail="session saved")


@router.delete("/{token}", dependencies=GUARDED)
async def close_login(token: str, services: ServicesDep) -> Message:
    """Abandon a login session without saving it."""
    try:
        services.browser.get(token)
    except NoSuchLoginSession as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="that login session is not open"
        ) from exc
    await services.browser.close()
    return Message(detail="login session closed")


@router.websocket("/{token}/ws")
async def stream(websocket: WebSocket, token: str) -> None:
    """Carry the VNC protocol between the browser tab and the running X server."""
    services = websocket.app.state.services
    try:
        session = services.browser.get(token)
    except NoSuchLoginSession:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # noVNC negotiates the "binary" subprotocol; refusing it leaves the client waiting.
    await websocket.accept(subprotocol="binary")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", session.rfb_port)
    except OSError:
        logger.warning("could not reach the VNC server for site %s", session.site_id)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    services.browser.add_viewer(session)
    try:
        await pump(websocket, reader, writer)
    except WebSocketDisconnect:
        logger.debug("the login stream for site %s was closed by the browser", session.site_id)
    finally:
        # The idle clock restarts here: with the tab gone, an unsaved session is abandoned.
        services.browser.remove_viewer(session)
