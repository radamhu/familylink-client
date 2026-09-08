"""add deadline column and identity constraint to homework_entries

Revision ID: 006
Revises: 005
Create Date: 2026-09-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '006'
down_revision: str | Sequence[str] | None = '005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add deadline column and (child_id, subject, deadline) uniqueness."""
    op.add_column('homework_entries', sa.Column('deadline', sa.Date(), nullable=False))
    op.create_unique_constraint(
        'uq_homework_entries_child_subject_deadline',
        'homework_entries',
        ['child_id', 'subject', 'deadline'],
    )


def downgrade() -> None:
    """Drop deadline column and its uniqueness constraint."""
    op.drop_constraint(
        'uq_homework_entries_child_subject_deadline',
        'homework_entries',
        type_='unique',
    )
    op.drop_column('homework_entries', 'deadline')
