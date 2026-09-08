"""add ekreta_credentials and homework_entries tables

Revision ID: 005
Revises: 004
Create Date: 2026-09-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '005'
down_revision: str | Sequence[str] | None = '004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ekreta_credentials and homework_entries tables."""
    op.create_table(
        'ekreta_credentials',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('child_id', sa.String(length=64), nullable=False),
        sa.Column('username', sa.String(length=256), nullable=False),
        sa.Column('password', sa.String(length=256), nullable=False),
        sa.Column('institution_code', sa.String(length=32), nullable=False),
    )
    op.create_unique_constraint(
        'uq_ekreta_credentials_child_id', 'ekreta_credentials', ['child_id']
    )
    op.create_table(
        'homework_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('child_id', sa.String(length=64), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('subject', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_homework_entries_child_id', 'homework_entries', ['child_id'])
    op.create_index(
        'ix_homework_entries_child_date', 'homework_entries', ['child_id', 'date']
    )


def downgrade() -> None:
    """Drop ekreta_credentials and homework_entries tables."""
    op.drop_index('ix_homework_entries_child_date', table_name='homework_entries')
    op.drop_index('ix_homework_entries_child_id', table_name='homework_entries')
    op.drop_table('homework_entries')
    op.drop_constraint(
        'uq_ekreta_credentials_child_id', 'ekreta_credentials', type_='unique'
    )
    op.drop_table('ekreta_credentials')
