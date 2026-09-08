from datetime import date

import kreta_client
import pytest
from config import Kid
from kreta_client import (
    KretaClientError,
    fetch_homework,
    parse_homework_entry,
    today_weekday_index,
)


def make_kid() -> Kid:
    return Kid(
        child_id="child1", username="u", password="p", institution_code="035120"
    )


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
        "deadline": " 2026. 09. 08. ",
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
    raw = {
        "subject": "Matek",
        "teacher": "X",
        "deadline": "2026. 09. 08.",
        "text": "p.23",
    }
    assert parse_homework_entry(raw)["attachments"] == []


def test_parse_homework_entry_raises_on_unparseable_deadline():
    raw = {"subject": "Matek", "teacher": "X", "deadline": "not a date", "text": ""}
    with pytest.raises(KretaClientError):
        parse_homework_entry(raw)


class TestParseHunDate:
    def test_dotted_with_spaces(self):
        assert kreta_client._parse_hun_date("2026. 09. 08.") == date(2026, 9, 8)

    def test_dotted_no_spaces(self):
        assert kreta_client._parse_hun_date("2026.09.08.") == date(2026, 9, 8)

    def test_iso_fallback(self):
        assert kreta_client._parse_hun_date("2026-09-08") == date(2026, 9, 8)

    def test_raises_on_garbage(self):
        with pytest.raises(KretaClientError):
            kreta_client._parse_hun_date("nem dátum")


class TestMergeHomeworkEntries:
    def test_same_key_collapses_and_keeps_richer_text(self):
        entries = [
            {
                "subject": "Matek",
                "teacher": "",
                "deadline": "2026-09-10",
                "text": "short",
                "attachments": ["a.pdf"],
            },
            {
                "subject": "Matek",
                "teacher": "Kovács Béla",
                "deadline": "2026-09-10",
                "text": "much longer description",
                "attachments": ["b.pdf"],
            },
        ]
        merged = kreta_client._merge_homework_entries(entries)
        assert len(merged) == 1
        assert merged[0]["text"] == "much longer description"
        assert merged[0]["teacher"] == "Kovács Béla"
        assert merged[0]["attachments"] == ["a.pdf", "b.pdf"]

    def test_different_subject_or_deadline_stays_separate(self):
        entries = [
            {
                "subject": "Matek",
                "teacher": "",
                "deadline": "2026-09-10",
                "text": "a",
                "attachments": [],
            },
            {
                "subject": "Angol",
                "teacher": "",
                "deadline": "2026-09-10",
                "text": "b",
                "attachments": [],
            },
            {
                "subject": "Matek",
                "teacher": "",
                "deadline": "2026-09-11",
                "text": "c",
                "attachments": [],
            },
        ]
        merged = kreta_client._merge_homework_entries(entries)
        assert len(merged) == 3


class TestFilterUpcoming:
    def test_drops_past_deadlines_keeps_today_and_future(self):
        entries = [
            {"subject": "Past", "deadline": "2026-09-07"},
            {"subject": "Today", "deadline": "2026-09-08"},
            {"subject": "Future", "deadline": "2026-09-09"},
        ]
        result = kreta_client._filter_upcoming(entries, date(2026, 9, 8))
        assert [e["subject"] for e in result] == ["Today", "Future"]


class TestFetchHomeworkOrchestration:
    def test_opens_menu_exactly_once_before_either_source(self, monkeypatch):
        """Confirmed flow: bejelentkezés -> Elektronikus ellenőrzőkönyv (once)
        -> Órarend or Házi feladatok (sibling leaves). Each source used to
        re-click the parent itself, which times out on the second visit
        because it's an accordion toggle, not a stateless link."""
        calls = []
        monkeypatch.setattr(kreta_client, "_login", lambda page, kid: None)
        monkeypatch.setattr(
            kreta_client, "_open_electronikus_ellenorzokonyv", lambda page: calls.append(page)
        )
        monkeypatch.setattr(kreta_client, "_scrape_orarend", lambda page, kid: [])
        monkeypatch.setattr(kreta_client, "_scrape_haza_feladatok", lambda page, kid: [])
        monkeypatch.setattr(kreta_client, "date", _FixedDate)
        fetch_homework(page=None, kid=make_kid())
        assert len(calls) == 1

    def test_merges_both_sources_and_filters(self, monkeypatch):
        monkeypatch.setattr(kreta_client, "_login", lambda page, kid: None)
        monkeypatch.setattr(
            kreta_client, "_open_electronikus_ellenorzokonyv", lambda page: None
        )
        monkeypatch.setattr(
            kreta_client,
            "_scrape_orarend",
            lambda page, kid: [
                {
                    "subject": "Matek",
                    "teacher": "",
                    "deadline": "2026-09-10",
                    "text": "a",
                    "attachments": [],
                }
            ],
        )
        monkeypatch.setattr(
            kreta_client,
            "_scrape_haza_feladatok",
            lambda page, kid: [
                {
                    "subject": "Angol",
                    "teacher": "",
                    "deadline": "2026-09-01",
                    "text": "expired",
                    "attachments": [],
                }
            ],
        )
        monkeypatch.setattr(kreta_client, "date", _FixedDate)
        result = fetch_homework(page=None, kid=make_kid())
        assert [e["subject"] for e in result] == ["Matek"]

    def test_one_source_failing_does_not_drop_the_other(self, monkeypatch):
        monkeypatch.setattr(kreta_client, "_login", lambda page, kid: None)
        monkeypatch.setattr(
            kreta_client, "_open_electronikus_ellenorzokonyv", lambda page: None
        )

        def raising_orarend(page, kid):
            raise RuntimeError("weekend / no orarend view")

        monkeypatch.setattr(kreta_client, "_scrape_orarend", raising_orarend)
        monkeypatch.setattr(
            kreta_client,
            "_scrape_haza_feladatok",
            lambda page, kid: [
                {
                    "subject": "Angol",
                    "teacher": "",
                    "deadline": "2026-09-10",
                    "text": "still works",
                    "attachments": [],
                }
            ],
        )
        monkeypatch.setattr(kreta_client, "date", _FixedDate)
        result = fetch_homework(page=None, kid=make_kid())
        assert [e["subject"] for e in result] == ["Angol"]


class _FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 9, 8)
