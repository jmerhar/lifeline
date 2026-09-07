"""Reading and changing the instance settings."""

from fastapi import APIRouter, Depends

from ...schemas import Message, SettingsRead, SettingsWrite
from ...services import logs
from ...services.notifier import Event
from ...services.store import load_settings_row
from ..deps import DbDep, ServicesDep, require_setup_complete, require_user

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(require_setup_complete), Depends(require_user)],
)


@router.get("")
async def show(db: DbDep) -> SettingsRead:
    """The current settings."""
    return SettingsRead.model_validate(await load_settings_row(db))


@router.put("")
async def update(payload: SettingsWrite, db: DbDep) -> SettingsRead:
    """Replace the settings."""
    row = await load_settings_row(db)
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    await db.flush()
    # Applied at once rather than at the next restart: the reason to change the level is to watch
    # something that is happening now.
    logs.apply_level(row.log_level)
    return SettingsRead.model_validate(row)


@router.post("/test-notification")
async def test_notification(db: DbDep, services: ServicesDep) -> Message:
    """Send a test message to every configured destination."""
    row = await load_settings_row(db)
    delivered = await services.notifier.notify(row, Event.TEST)
    if delivered:
        return Message(detail="test notification sent")
    return Message(
        detail="nothing was sent: check that at least one destination is configured and valid"
    )
