"""The record of one ping."""

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UtcDateTime
from .enums import CheckOutcome, enum_column
from .site import Site


class Check(Base):
    """What happened when a site was last pinged, kept as history.

    Rows are pruned by the retention setting: the value of old checks is the shape of
    the recent trend, not an audit trail, and an unbounded table on a home server is a
    disk-space problem waiting to happen.
    """

    __tablename__ = "checks"
    __table_args__ = (
        # Every read of this table is "the newest rows for one site" — the pulse strip in
        # the site list, and the history page.
        Index("ix_checks_site_id_started_at", "site_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)

    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    outcome: Mapped[CheckOutcome] = mapped_column(enum_column(CheckOutcome))
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    final_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # Why the outcome is what it is, in a sentence a person can act on.
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    site: Mapped[Site] = relationship(back_populates="checks")
