"""The history view across every site."""

from fastapi import APIRouter
from sqlalchemy import select

from ...models import Check
from ...schemas import CheckRead
from ..deps import DbDep

router = APIRouter(prefix="/checks", tags=["checks"])

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


@router.get("")
async def index(db: DbDep, limit: int = DEFAULT_LIMIT) -> list[CheckRead]:
    """The most recent checks across all sites, newest first."""
    result = await db.execute(
        select(Check)
        .order_by(Check.started_at.desc(), Check.id.desc())
        .limit(min(max(limit, 1), MAX_LIMIT))
    )
    return [CheckRead.model_validate(check) for check in result.scalars()]
