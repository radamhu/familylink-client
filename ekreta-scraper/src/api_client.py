"""Posts scraped homework results back to familylink-server."""

import httpx


def post_homework(
    api_url: str, token: str, child_id: str, entries: list[dict]
) -> None:
    """POST one kid's scraped, not-yet-due homework to familylink-server."""
    resp = httpx.post(
        f'{api_url}/internal/ekreta/homework',
        headers={'X-Api-Key': token},
        json={'child_id': child_id, 'entries': entries},
        timeout=30,
    )
    resp.raise_for_status()
