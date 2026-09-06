"""The single administrator account."""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UtcDateTime


class User(Base, TimestampMixin):
    """Whoever set the instance up.

    One account is all this tool needs: it manages one person's logins, and every extra
    user would be another way into the same session store.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
