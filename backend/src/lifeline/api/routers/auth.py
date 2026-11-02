"""Logging in and out."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from ...models import User
from ...schemas import LoginRequest, Message, UserRead
from ..deps import DbDep, ServicesDep, UserDep
from ..security import burn_password_check, verify_password
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
    """Check a password and log the browser in.

    Only failures count against the throttle, so logging in and out again is never refused.
    """
    client = _client_key(request)
    if services.throttle.blocked(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts; wait a minute and try again",
        )

    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if user is None:
        # As slow as a wrong password, so timing does not tell which usernames exist.
        burn_password_check(payload.password)
    # The same message either way: saying which half was wrong tells an unauthenticated
    # caller whether a username exists.
    if user is None or not verify_password(user.password_hash, payload.password):
        services.throttle.failed(client)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect username or password"
        )

    services.throttle.succeeded(client)
    user.last_login_at = datetime.now(UTC)
    token = await services.sessions.open(db, user.id, request.headers.get("user-agent", ""))
    issue_session_cookie(response, services, token, request)
    return UserRead.model_validate(user)


@router.post("/logout")
async def logout(request: Request, response: Response, db: DbDep, services: ServicesDep) -> Message:
    """Log the browser out, ending its session so the cookie cannot be used again."""
    token = request.cookies.get(services.settings.session_cookie_name)
    if token:
        await services.sessions.end(db, token)
    clear_session_cookie(response, services, request)
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
