"""Record what a session holds in local storage, not only its cookies.

Revision ID: 2b0062eb24f6
Revises: 4b08b261a1e7
Create Date: 2026-09-10 14:30:36.138117
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '2b0062eb24f6'
down_revision: str | None = '4b08b261a1e7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('site_sessions', schema=None) as batch_op:
        # A server default, because the column is not nullable and every session already stored
        # needs a value for it. Empty is honest for those: what they hold is not recorded until
        # their next capture or write-back, and the interface reads an empty list as "not known"
        # rather than as "nothing there".
        batch_op.add_column(
            sa.Column('storage_names', sa.Text(), nullable=False, server_default='')
        )


def downgrade() -> None:
    with op.batch_alter_table('site_sessions', schema=None) as batch_op:
        batch_op.drop_column('storage_names')
