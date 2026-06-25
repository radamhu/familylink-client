"""add bonus_mins to linux_usage_snapshots

Revision ID: 003
Revises: 002
Create Date: 2026-06-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bonus_mins column to linux_usage_snapshots."""
    op.add_column(
        "linux_usage_snapshots",
        sa.Column("bonus_mins", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Drop bonus_mins column from linux_usage_snapshots."""
    op.drop_column("linux_usage_snapshots", "bonus_mins")
