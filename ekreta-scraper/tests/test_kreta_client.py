from datetime import date

import pytest

from kreta_client import KretaClientError, parse_homework_entry, today_weekday_index


def test_today_weekday_index_monday():
    assert today_weekday_index(date(2026, 9, 7)) == 0  # Monday


def test_today_weekday_index_friday():
    assert today_weekday_index(date(2026, 9, 11)) == 4  # Friday


def test_today_weekday_index_saturday_raises():
    with pytest.raises(KretaClientError):
        today_weekday_index(date(2026, 9, 12))  # Saturday


def test_parse_homework_entry_full():
    raw = {
        "subject": " Matematika ",
        "teacher": " Kovács Béla ",
        "deadline": " 2026-09-08 ",
        "text": " 23. oldal, 4-5. feladat ",
        "attachments": ["worksheet.pdf"],
    }
    assert parse_homework_entry(raw) == {
        "subject": "Matematika",
        "teacher": "Kovács Béla",
        "deadline": "2026-09-08",
        "text": "23. oldal, 4-5. feladat",
        "attachments": ["worksheet.pdf"],
    }


def test_parse_homework_entry_missing_attachments_defaults_empty():
    raw = {"subject": "Matek", "teacher": "X", "deadline": "2026-09-08", "text": "p.23"}
    assert parse_homework_entry(raw)["attachments"] == []
