"""add auto-block and bonus columns to app_configs

Revision ID: 004
Revises: 003
Create Date: 2026-07-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '004'
down_revision: str | Sequence[str] | None = '003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add auto_block_enabled, auto_blocked_at, bonus_mins, bonus_date to app_configs."""
    op.add_column(
        'app_configs',
        sa.Column(
            'auto_block_enabled', sa.Boolean(), nullable=False, server_default='false'
        ),
    )
    op.add_column(
        'app_configs',
        sa.Column('auto_blocked_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'app_configs',
        sa.Column('bonus_mins', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'app_configs',
        sa.Column('bonus_date', sa.Date(), nullable=True),
    )
    op.create_unique_constraint(
        'uq_app_configs_child_package', 'app_configs', ['child_id', 'package_name']
    )


def downgrade() -> None:
    """Drop auto-block and bonus columns from app_configs."""
    op.drop_constraint('uq_app_configs_child_package', 'app_configs', type_='unique')
    op.drop_column('app_configs', 'bonus_date')
    op.drop_column('app_configs', 'bonus_mins')
    op.drop_column('app_configs', 'auto_blocked_at')
    op.drop_column('app_configs', 'auto_block_enabled')
