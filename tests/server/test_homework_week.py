"""Tests for the pure weekly homework builder."""

from datetime import date
from types import SimpleNamespace

from familylink_server.services.homework_week import build_week, week_start

TODAY = date(2026, 10, 16)  # Friday; week Mon 12 .. Sun 18


def _e(subject, registered_on, deadline, seen=None):
    return SimpleNamespace(
        subject=subject,
        description=f'{subject} desc',
        deadline=deadline,
        registered_on=registered_on,
        date=seen or registered_on,
    )


def _col(week, label):
    return next(c for c in week.columns if c.label == label)


def _subjects(week, label):
    return [c.subject for c in _col(week, label).cells]


def test_week_start_is_monday():
    assert week_start(date(2026, 10, 18)) == date(2026, 10, 12)
    assert week_start(date(2026, 10, 12)) == date(2026, 10, 12)


def test_no_entries_returns_none():
    assert build_week([], TODAY) is None


def test_columns_layout():
    week = build_week([_e('Matek', date(2026, 10, 13), date(2026, 10, 15))], TODAY)
    assert [c.label for c in week.columns] == [
        'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Weekend'
    ]  # fmt: skip
    assert _col(week, 'Mon').day == date(2026, 10, 12)
    assert _col(week, 'Weekend').day is None


def test_entry_in_registration_day_column_and_dimmed():
    week = build_week([_e('Matek', date(2026, 10, 13), date(2026, 10, 15))], TODAY)
    assert _subjects(week, 'Tue') == ['Matek']
    cell = _col(week, 'Tue').cells[0]
    assert cell.dimmed and not cell.due_today and not cell.to_weekend
    assert cell.description == 'Matek desc'


def test_today_column_flagged():
    week = build_week([_e('Angol', date(2026, 10, 14), date(2026, 10, 16))], TODAY)
    assert [c.label for c in week.columns if c.is_today] == ['Fri']


def test_due_today_flag():
    week = build_week([_e('Angol', date(2026, 10, 14), date(2026, 10, 16))], TODAY)
    cell = _col(week, 'Wed').cells[0]
    assert cell.due_today and not cell.dimmed


def test_later_week_deadline_gets_weekend_copy():
    week = build_week([_e('Tori', date(2026, 10, 15), date(2026, 10, 19))], TODAY)
    thu = _col(week, 'Thu').cells[0]
    assert thu.to_weekend and not thu.is_weekend_copy
    wk = _col(week, 'Weekend').cells
    assert [(c.subject, c.deadline, c.is_weekend_copy) for c in wk] == [
        ('Tori', date(2026, 10, 19), True)
    ]


def test_weekend_registration_has_no_duplicate_copy():
    week = build_week([_e('Fizika', date(2026, 10, 17), date(2026, 10, 21))], TODAY)
    assert _subjects(week, 'Weekend') == ['Fizika']
    assert all(not c.cells for c in week.columns if c.label != 'Weekend')


def test_carryover_due_in_shown_week_goes_to_deadline_day():
    rows = [
        _e('Carry', date(2026, 10, 9), date(2026, 10, 14), seen=date(2026, 10, 12)),
    ]
    week = build_week(rows, TODAY)
    assert _subjects(week, 'Wed') == ['Carry']


def test_carryover_due_later_goes_weekend_only():
    rows = [_e('Carry', date(2026, 10, 9), date(2026, 10, 22), seen=date(2026, 10, 12))]
    week = build_week(rows, TODAY)
    assert _subjects(week, 'Weekend') == ['Carry']
    assert sum(len(c.cells) for c in week.columns) == 1


def test_carryover_due_on_weekend_of_shown_week_goes_weekend():
    rows = [_e('Carry', date(2026, 10, 9), date(2026, 10, 17), seen=date(2026, 10, 12))]
    week = build_week(rows, TODAY)
    assert _subjects(week, 'Weekend') == ['Carry']


def test_stale_row_before_week_skipped():
    rows = [
        _e('Stale', date(2026, 10, 5), date(2026, 10, 7), seen=date(2026, 10, 6)),
        _e('Fresh', date(2026, 10, 13), date(2026, 10, 15)),
    ]
    week = build_week(rows, TODAY)
    assert sum(len(c.cells) for c in week.columns) == 1
    assert _subjects(week, 'Tue') == ['Fresh']


def test_monday_before_scrape_keeps_old_week_no_highlight():
    monday = date(2026, 10, 19)
    week = build_week([_e('Matek', date(2026, 10, 13), date(2026, 10, 15))], monday)
    assert _col(week, 'Mon').day == date(2026, 10, 12)
    assert not any(c.is_today for c in week.columns)


def test_saturday_highlights_weekend_column():
    week = build_week(
        [_e('Matek', date(2026, 10, 13), date(2026, 10, 15))], date(2026, 10, 17)
    )
    assert [c.label for c in week.columns if c.is_today] == ['Weekend']


def test_rollover_uses_last_seen_date():
    monday = date(2026, 10, 19)
    rows = [_e('Tori', date(2026, 10, 16), monday, seen=monday)]
    week = build_week(rows, monday)
    assert _col(week, 'Mon').day == monday
    assert _subjects(week, 'Mon') == ['Tori']
    assert _col(week, 'Mon').is_today
    assert _col(week, 'Mon').cells[0].due_today


def test_cells_sorted_by_subject():
    rows = [
        _e('Zene', date(2026, 10, 13), date(2026, 10, 20)),
        _e('Angol', date(2026, 10, 13), date(2026, 10, 20)),
    ]
    assert _subjects(build_week(rows, TODAY), 'Tue') == ['Angol', 'Zene']
