"""Tests for the shared get_or_create_app_config DB helper."""

from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError

from familylink_server.db.app_config import get_or_create_app_config
from familylink_server.db.models import AppConfig


async def test_get_or_create_app_config_retries_after_integrity_error():
    """A concurrent insert race (unique constraint violation) is resolved by re-querying."""
    winner = AppConfig(
        child_id='child1',
        app_name='com.google.android.youtube',
        package_name='com.google.android.youtube',
    )

    no_existing_row = MagicMock()
    no_existing_row.scalar_one_or_none.return_value = None

    post_rollback_row = MagicMock()
    post_rollback_row.scalar_one.return_value = winner

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[no_existing_row, post_rollback_row])
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock(
        side_effect=IntegrityError('statement', {}, Exception('duplicate key'))
    )
    mock_session.rollback = AsyncMock()

    result = await get_or_create_app_config(
        mock_session, 'child1', 'com.google.android.youtube'
    )

    mock_session.rollback.assert_awaited_once()
    assert result is winner
    assert mock_session.execute.await_count == 2
