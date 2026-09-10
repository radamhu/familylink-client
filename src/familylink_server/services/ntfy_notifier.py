"""Outbound ntfy push notification service."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# ntfy's JSON publish API requires `priority` as an integer 1-5 (unlike the
# header-based publish API, which also accepts these string keywords) — a
# string value here makes the whole request body invalid JSON to ntfy and
# every push fails with 400. See https://docs.ntfy.sh/publish/#message-priority
_PRIORITY_LEVELS = {'min': 1, 'low': 2, 'default': 3, 'high': 4, 'urgent': 5, 'max': 5}


class NtfyNotifier:
    """Sends push notifications to per-kid topics on a (self-hosted) ntfy server.

    Uses ntfy's JSON publish API (a single POST to `base_url` with the topic
    in the body) rather than the per-topic-URL header API — the header API
    can't safely carry UTF-8 (emoji titles) since HTTP headers are
    effectively ASCII/latin-1.
    """

    def __init__(self, topics: dict[str, str], base_url: str) -> None:
        self._topics = topics
        self._base_url = base_url

    async def send(
        self,
        child_id: str,
        title: str,
        message: str,
        priority: str = 'default',
        tags: list[str] | None = None,
    ) -> None:
        """POST a notification for `child_id`. No-op if that kid has no topic mapped."""
        topic = self._topics.get(child_id)
        if not topic:
            return
        payload: dict[str, object] = {
            'topic': topic,
            'title': title,
            'message': message,
            'priority': _PRIORITY_LEVELS.get(priority, _PRIORITY_LEVELS['default']),
        }
        if tags:
            payload['tags'] = tags
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self._base_url, json=payload, timeout=10)
                resp.raise_for_status()
        except Exception:
            logger.warning('ntfy push failed for child %s', child_id, exc_info=True)

    async def notify_homework(self, child_id: str, subject: str, deadline: str) -> None:
        """Push a new-homework alert."""
        await self.send(
            child_id,
            title=f'📚 New homework — {subject}',
            message=f'Due {deadline}',
            tags=['book'],
        )

    async def notify_low_time(
        self, child_id: str, target_name: str, remaining_mins: int
    ) -> None:
        """Push a low-remaining-time warning."""
        await self.send(
            child_id,
            title=f'⏰ {target_name}: {remaining_mins} min left',
            message=(
                f'{target_name} will lock soon — '
                f'{remaining_mins} minutes remaining today.'
            ),
            priority='high',
            tags=['hourglass'],
        )


_notifier: NtfyNotifier | None = None


def init_notifier(topics: dict[str, str], base_url: str) -> NtfyNotifier:
    """Create and store the singleton. Called once in lifespan."""
    global _notifier
    _notifier = NtfyNotifier(topics, base_url)
    return _notifier


def get_notifier() -> NtfyNotifier | None:
    """Return the singleton, or None when no topics are configured."""
    return _notifier
