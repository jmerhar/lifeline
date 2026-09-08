"""Initial schema: sites, their captured sessions, check history, settings and the admin user.

Revision ID: b1422975d000
Revises: 
Create Date: 2026-09-06 23:18:30.740893
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b1422975d000'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('apprise_urls', sa.Text(), nullable=False),
    sa.Column('notify_on_lapsed', sa.Boolean(), nullable=False),
    sa.Column('notify_on_recovered', sa.Boolean(), nullable=False),
    sa.Column('notify_on_errors', sa.Boolean(), nullable=False),
    sa.Column('notify_on_cookie_expiry', sa.Boolean(), nullable=False),
    sa.Column('notify_on_deadline', sa.Boolean(), nullable=False),
    sa.Column('notify_cooldown_hours', sa.Integer(), nullable=False),
    sa.Column('warning_lead_days', sa.Integer(), nullable=False),
    sa.Column('error_threshold', sa.Integer(), nullable=False),
    sa.Column('default_interval_days', sa.Integer(), nullable=False),
    sa.Column('retention_days', sa.Integer(), nullable=False),
    sa.Column('browser_idle_timeout_minutes', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('id = 1', name=op.f('ck_settings_singleton')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_settings'))
    )
    op.create_table('sites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('ping_url', sa.String(length=2048), nullable=False),
    sa.Column('login_url', sa.String(length=2048), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('interval_days', sa.Integer(), nullable=False),
    sa.Column('jitter_percent', sa.Integer(), nullable=False),
    sa.Column('ping_method', sa.Enum('http', 'browser', name='pingmethod', native_enum=False), nullable=False),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('favicon', sa.Text(), nullable=True),
    sa.Column('expected_status', sa.Integer(), nullable=False),
    sa.Column('follow_redirects', sa.Boolean(), nullable=False),
    sa.Column('login_url_pattern', sa.String(length=512), nullable=True),
    sa.Column('success_pattern', sa.String(length=512), nullable=True),
    sa.Column('failure_pattern', sa.String(length=512), nullable=True),
    sa.Column('inactivity_limit_days', sa.Integer(), nullable=True),
    sa.Column('status', sa.Enum('unknown', 'alive', 'at_risk', 'lapsed', 'error', name='sitestatus', native_enum=False), nullable=False),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('last_check_at', sa.DateTime(), nullable=True),
    sa.Column('last_ok_at', sa.DateTime(), nullable=True),
    sa.Column('next_check_at', sa.DateTime(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sites')),
    sa.UniqueConstraint('name', name=op.f('uq_sites_name'))
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username'))
    )
    op.create_table('checks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('outcome', sa.Enum('ok', 'login_expired', 'pattern_missing', 'http_error', 'network_error', name='checkoutcome', native_enum=False), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('final_url', sa.String(length=2048), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_checks_site_id_sites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_checks'))
    )
    with op.batch_alter_table('checks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_checks_site_id'), ['site_id'], unique=False)
        batch_op.create_index('ix_checks_site_id_started_at', ['site_id', 'started_at'], unique=False)

    op.create_table('site_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('state', sa.LargeBinary(), nullable=False),
    sa.Column('captured_via', sa.Enum('browser', 'import', name='capturemethod', native_enum=False), nullable=False),
    sa.Column('captured_at', sa.DateTime(), nullable=False),
    sa.Column('rotated_at', sa.DateTime(), nullable=True),
    sa.Column('earliest_expiry', sa.DateTime(), nullable=True),
    sa.Column('cookie_names', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['site_id'], ['sites.id'], name=op.f('fk_site_sessions_site_id_sites'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_site_sessions')),
    sa.UniqueConstraint('site_id', name=op.f('uq_site_sessions_site_id'))
    )


def downgrade() -> None:
    op.drop_table('site_sessions')
    with op.batch_alter_table('checks', schema=None) as batch_op:
        batch_op.drop_index('ix_checks_site_id_started_at')
        batch_op.drop_index(batch_op.f('ix_checks_site_id'))

    op.drop_table('checks')
    op.drop_table('users')
    op.drop_table('sites')
    op.drop_table('settings')
