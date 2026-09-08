"""Tests for the config module."""

import httpx
import pytest
from config import Kid, fetch_kids, load_cron_schedule


def test_fetch_kids_parses_response(monkeypatch):
    """Test that fetch_kids parses response JSON into Kid instances."""

    def fake_get(url, headers=None, timeout=None):
        assert url == 'http://familylink-web:8000/internal/ekreta/credentials'
        assert headers == {'X-Api-Key': 'secret-token'}
        return httpx.Response(
            200,
            json=[
                {
                    'child_id': 'child1',
                    'username': 'anna.kovacs',
                    'password': 'pw',
                    'institution_code': '035120',
                }
            ],
            request=httpx.Request('GET', url),
        )

    monkeypatch.setattr(httpx, 'get', fake_get)
    kids = fetch_kids('http://familylink-web:8000', 'secret-token')
    assert kids == [
        Kid(
            child_id='child1',
            username='anna.kovacs',
            password='pw',
            institution_code='035120',
        )
    ]


def test_fetch_kids_raises_on_http_error(monkeypatch):
    """Test that fetch_kids raises on HTTP error status."""

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            401, json={'detail': 'Unauthorized'}, request=httpx.Request('GET', url)
        )

    monkeypatch.setattr(httpx, 'get', fake_get)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_kids('http://familylink-web:8000', 'wrong-token')


def test_load_cron_schedule_default():
    """Test that load_cron_schedule returns default schedule."""
    assert load_cron_schedule({}) == '0 6 * * 1-5'


def test_load_cron_schedule_override():
    """Test that load_cron_schedule returns override value from env."""
    assert load_cron_schedule({'CRON_SCHEDULE': '0 7 * * *'}) == '0 7 * * *'
