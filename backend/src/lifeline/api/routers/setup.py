"""The first-run wizard."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from ...models import User
from ...schemas import SetupRequest, SetupState, UserRead
from ...services.store import load_settings_row
from ..security import PasswordTooShort, hash_password
from ..session import issue_session_cookie
from ..deps import DbDep, ServicesDep

router = APIRouter(prefix="/setup", tags=["setup"])


async def _user_count(db: DbDep) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


@router.get("")
async def state(db: DbDep, services: ServicesDep, request: Request) -> SetupState:
    """Whether this instance still needs an administrator."""
    return SetupState(
        setup_required=await _user_count(db) == 0,
        token_required=request.app.state.setup_token is not None,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def complete(
    payload: SetupRequest,
    db: DbDep,
    services: ServicesDep,
    request: Request,
    response: Response,
) -> UserRead:
    """Create the administrator and log the browser in.

    Guarded by a token printed to the container's log. This instance may be reachable from
    the internet before anyone has configured it, and without the token whoever found the
    URL first would own it.
    """
    if await _user_count(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this instance is already set up"
        )

    expected = request.app.state.setup_token
    if expected is not None and payload.token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="the setup token does not match the one in the container log",
        )

    try:
        password_hash = hash_password(payload.password)
    except PasswordTooShort as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    user = User(username=payload.username.strip(), password_hash=password_hash)
    db.add(user)
    # The settings row is created here so that the rest of the application can rely on it
    # existing rather than each caller having to allow for its absence.
    await load_settings_row(db)
    await db.flush()

    # The token is single-use: setup is complete, so nothing may run it again.
    request.app.state.setup_token = None
    issue_session_cookie(response, services, user.id, request)
    return UserRead.model_validate(user)
