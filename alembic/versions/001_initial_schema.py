"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-19 15:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create app_configs table
    op.create_table(
        "app_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.String(64), nullable=False),
        sa.Column("app_name", sa.String(256), nullable=False),
        sa.Column("package_name", sa.String(256), nullable=False),
        sa.Column("max_mins", sa.Integer(), nullable=True),
        sa.Column("days_mask", sa.String(64), nullable=False, server_default=""),
        sa.Column("time_range", sa.String(32), nullable=False, server_default=""),
        sa.Column(
            "always_allowed", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_app_configs_child_id"), "app_configs", ["child_id"], unique=False
    )

    # Create usage_snapshots table
    op.create_table(
        "usage_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.String(64), nullable=False),
        sa.Column("app_package", sa.String(256), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("usage_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("device_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_usage_snapshots_child_id"),
        "usage_snapshots",
        ["child_id"],
        unique=False,
    )

    # Create device_snapshots table
    op.create_table(
        "device_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("child_id", sa.String(64), nullable=False),
        sa.Column("friendly_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id"),
    )

    # Create audit_log table
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(256), nullable=False, server_default=""),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_log_child_id"), "audit_log", ["child_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_audit_log_child_id"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("device_snapshots")
    op.drop_index(op.f("ix_usage_snapshots_child_id"), table_name="usage_snapshots")
    op.drop_table("usage_snapshots")
    op.drop_index(op.f("ix_app_configs_child_id"), table_name="app_configs")
    op.drop_table("app_configs")
