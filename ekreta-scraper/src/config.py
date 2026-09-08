"""Kid config fetched from familylink-server's internal API."""

from collections.abc import Mapping
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Kid:
    """A kid's eKRÉTA credentials and metadata."""

    child_id: str
    username: str
    password: str
    institution_code: str


def fetch_kids(api_url: str, token: str) -> list[Kid]:
    """Fetch the configured kid list from familylink-server's internal API."""
    resp = httpx.get(
        f'{api_url}/internal/ekreta/credentials',
        headers={'X-Api-Key': token},
        timeout=30,
    )
    resp.raise_for_status()
    return [Kid(**row) for row in resp.json()]


def load_cron_schedule(env: Mapping[str, str]) -> str:
    """Load cron schedule from environment or use default."""
    return env.get('CRON_SCHEDULE', '0 6 * * 1-5')
