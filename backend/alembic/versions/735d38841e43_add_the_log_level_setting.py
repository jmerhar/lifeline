"""Add the log level, so it can be changed without restarting the container.

Revision ID: 735d38841e43
Revises: b1422975d000
Create Date: 2026-09-07 03:32:43.824959
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '735d38841e43'
down_revision: str | None = 'b1422975d000'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        # A server default, because the column is not nullable and an existing instance already
        # has a settings row that needs a value for it.
        batch_op.add_column(
            sa.Column('log_level', sa.String(length=10), nullable=False, server_default='INFO')
        )



def downgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('log_level')

