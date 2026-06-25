"""add linux_machines and linux_usage_snapshots tables

Revision ID: 002
Revises: 001
Create Date: 2026-06-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: str | Sequence[str] | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add linux_machines and linux_usage_snapshots."""
    op.create_table(
        "linux_machines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.String(64), nullable=False),
        sa.Column("friendly_name", sa.String(256), nullable=False),
        sa.Column("hostname", sa.String(256), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("ssh_user", sa.String(64), nullable=False),
        sa.Column("ssh_private_key", sa.Text(), nullable=False),
        sa.Column("daily_limit_mins", sa.Integer(), nullable=True),
        sa.Column(
            "grace_period_mins", sa.Integer(), nullable=False, server_default="5"
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "linux_usage_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("machine_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("active_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("poweroff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id"], ["linux_machines.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "date"),
    )


def downgrade() -> None:
    """Drop linux_machines and linux_usage_snapshots."""
    op.drop_table("linux_usage_snapshots")
    op.drop_table("linux_machines")
