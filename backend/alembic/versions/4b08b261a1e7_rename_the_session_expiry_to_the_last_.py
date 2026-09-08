"""Record when the *last* stored cookie expires, not the first.

Dropped and re-added rather than renamed. The old column held the soonest expiry among the
stored cookies, which on a real login page is some analytics cookie with a fifteen-minute life —
it answered a different question, so carrying its value across would carry a wrong answer. Left
empty, it means 'no expiry known', which raises no warning; the next check fills it in.

Revision ID: 4b08b261a1e7
Revises: 735d38841e43
Create Date: 2026-09-08 17:36:18.678221
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '4b08b261a1e7'
down_revision: str | None = '735d38841e43'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("site_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch_op.drop_column("earliest_expiry")


def downgrade() -> None:
    with op.batch_alter_table("site_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("earliest_expiry", sa.DateTime(), nullable=True))
        batch_op.drop_column("expires_at")
