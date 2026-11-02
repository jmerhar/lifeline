"""The first-run wizard."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from ...models import User
from ...schemas import SetupRequest, SetupState, UserRead
from ...services.store import load_settings_row
from ..deps import DbDep, ServicesDep
from ..security import PasswordTooShort, hash_password
from ..session import issue_session_cookie

router = APIRouter(prefix="/setup", tags=["setup"])


async def _user_count(db: DbDep) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


@router.get("")
async def state(db: DbDep) -> SetupState:
    """Whether this instance still needs an administrator."""
    return SetupState(setup_required=await _user_count(db) == 0)


@router.post("", status_code=status.HTTP_201_CREATED)
async def complete(
    payload: SetupRequest,
    db: DbDep,
    services: ServicesDep,
    request: Request,
    response: Response,
) -> UserRead:
    """Create the administrator and log the browser in.

    Held under a lock, so two requests at once cannot both create an administrator.
    """
    async with services.setup_lock:
        return await _complete(payload, db, services, request, response)


async def _complete(
    payload: SetupRequest,
    db: DbDep,
    services: ServicesDep,
    request: Request,
    response: Response,
) -> UserRead:
    """Create the administrator, with the setup lock held."""
    if await _user_count(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this instance is already set up"
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

    token = await services.sessions.open(db, user.id, request.headers.get("user-agent", ""))
    issue_session_cookie(response, services, token, request)
    return UserRead.model_validate(user)
