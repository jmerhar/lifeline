"""The endpoint the container's health check calls."""

from fastapi import APIRouter
from sqlalchemy import text

from ... import __version__
from ..deps import DbDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DbDep) -> dict[str, str]:
    """Report that the process is up and its database is reachable.

    Unauthenticated, and it touches the database rather than only returning a constant: a
    container that answers while its database is unopenable is not healthy, and a probe
    that cannot tell the difference is worse than none.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected", "version": __version__}
