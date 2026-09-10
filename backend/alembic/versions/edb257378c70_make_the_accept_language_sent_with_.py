"""Make the Accept-Language sent with every check configurable.

Revision ID: edb257378c70
Revises: 2b0062eb24f6
Create Date: 2026-09-10 23:43:03.076398
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'edb257378c70'
down_revision: str | None = '2b0062eb24f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        # A server default, because the column is not nullable and an existing instance already
        # has a settings row that needs a value for it. English, because that is the language the
        # interface itself is written in.
        batch_op.add_column(
            sa.Column(
                'accept_language',
                sa.String(length=120),
                nullable=False,
                server_default='en-US,en;q=0.9',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('accept_language')
