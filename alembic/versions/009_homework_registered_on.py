"""add registered_on (first seen) to homework_entries

Revision ID: 009
Revises: 008
Create Date: 2026-10-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '009'
down_revision: str | Sequence[str] | None = '008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add registered_on, backfilled from the last-seen date."""
    op.add_column(
        'homework_entries', sa.Column('registered_on', sa.Date(), nullable=True)
    )
    op.execute('UPDATE homework_entries SET registered_on = date')
    op.alter_column('homework_entries', 'registered_on', nullable=False)


def downgrade() -> None:
    """Drop registered_on."""
    op.drop_column('homework_entries', 'registered_on')
