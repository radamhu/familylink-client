"""Tests for the api_client module."""

from datetime import date

import httpx
import pytest
from api_client import post_homework


def test_post_homework_sends_expected_payload(monkeypatch):
    """Test that post_homework sends expected payload."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['url'] = url
        captured['headers'] = headers
        captured['json'] = json
        return httpx.Response(204, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', fake_post)
    post_homework(
        'http://familylink-web:8000',
        'secret-token',
        'child1',
        date(2026, 9, 8),
        [{'subject': 'Matek'}],
    )
    assert captured['url'] == 'http://familylink-web:8000/internal/ekreta/homework'
    assert captured['headers'] == {'X-Api-Key': 'secret-token'}
    assert captured['json'] == {
        'child_id': 'child1',
        'date': '2026-09-08',
        'entries': [{'subject': 'Matek'}],
    }


def test_post_homework_raises_on_http_error(monkeypatch):
    """Test that post_homework raises on HTTP error status."""

    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(401, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', fake_post)
    with pytest.raises(httpx.HTTPStatusError):
        post_homework(
            'http://familylink-web:8000', 'bad', 'child1', date(2026, 9, 8), []
        )
