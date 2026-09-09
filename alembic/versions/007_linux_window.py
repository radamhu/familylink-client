"""add window_start_time and window_end_time to linux_machines

Revision ID: 007
Revises: 006
Create Date: 2026-09-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '007'
down_revision: str | Sequence[str] | None = '006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable bedtime-window columns to linux_machines."""
    op.add_column(
        'linux_machines', sa.Column('window_start_time', sa.Time(), nullable=True)
    )
    op.add_column(
        'linux_machines', sa.Column('window_end_time', sa.Time(), nullable=True)
    )


def downgrade() -> None:
    """Drop bedtime-window columns from linux_machines."""
    op.drop_column('linux_machines', 'window_end_time')
    op.drop_column('linux_machines', 'window_start_time')
