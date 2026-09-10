"""add low-time-alert tracking columns to app_configs and linux_usage_snapshots

Revision ID: 008
Revises: 007
Create Date: 2026-09-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '008'
down_revision: str | Sequence[str] | None = '007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable low-time-alert tracking columns."""
    op.add_column(
        'app_configs', sa.Column('low_time_alerted_date', sa.Date(), nullable=True)
    )
    op.add_column(
        'linux_usage_snapshots',
        sa.Column(
            'low_time_alerted',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Drop low-time-alert tracking columns."""
    op.drop_column('linux_usage_snapshots', 'low_time_alerted')
    op.drop_column('app_configs', 'low_time_alerted_date')
