"""Logging in and out."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from ...models import User
from ...schemas import LoginRequest, Message, UserRead
from ..deps import DbDep, ServicesDep, UserDep
from ..security import verify_password
from ..session import clear_session_cookie, issue_session_cookie

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    """What the login throttle counts attempts against."""
    return request.client.host if request.client else "unknown"


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    services: ServicesDep,
) -> UserRead:
    """Check a password and log the browser in."""
    client = _client_key(request)
    if not services.throttle.allow(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts; wait a minute and try again",
        )

    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    # The same message either way: saying which half was wrong tells an unauthenticated
    # caller whether a username exists.
    if user is None or not verify_password(user.password_hash, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect username or password"
        )

    services.throttle.reset(client)
    user.last_login_at = datetime.now(UTC)
    issue_session_cookie(response, services, user.id, request)
    return UserRead.model_validate(user)


@router.post("/logout")
async def logout(response: Response, services: ServicesDep) -> Message:
    """Log the browser out."""
    clear_session_cookie(response, services)
    return Message(detail="logged out")


@router.get("/me")
async def me(user: UserDep) -> UserRead:
    """Who is logged in.

    With authentication disabled there is no user to describe, so a placeholder is returned
    rather than a 401 the UI would read as "log in".
    """
    if user is None:
        return UserRead(id=0, username="anonymous", last_login_at=None)
    return UserRead.model_validate(user)
