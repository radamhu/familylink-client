"""Pure builder: turn a child's homework rows into a Mon-Fri + Weekend grid."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Weekend']
_WEEKEND = 5


@dataclass(frozen=True)
class HomeworkCell:
    """One homework item rendered inside a column."""

    subject: str
    description: str
    deadline: date
    dimmed: bool  # deadline < today
    due_today: bool  # deadline == today
    to_weekend: bool  # day-column original whose deadline is after the shown week
    is_weekend_copy: bool  # cell lives in the Weekend column (shows deadline tag)


@dataclass(frozen=True)
class WeekColumn:
    """A weekday column, or the single Weekend column (`day` is None)."""

    label: str
    day: date | None
    is_today: bool
    cells: list[HomeworkCell]


@dataclass(frozen=True)
class HomeworkWeek:
    """Exactly six columns: Mon..Fri, Weekend."""

    columns: list[WeekColumn]


def week_start(d: date) -> date:
    """Return the Monday of the week containing `d`."""
    return d - timedelta(days=d.weekday())


def build_week(entries: Sequence[Any], today: date) -> HomeworkWeek | None:
    """Build the shown week for a child, or None when there are no entries.

    The shown week is the Mon-Sun week of the most recent last-seen `date`.
    Entries expose `.subject .description .deadline .date .registered_on`.
    """
    if not entries:
        return None
    start = week_start(max(e.date for e in entries))
    end = start + timedelta(days=6)
    buckets: list[list[HomeworkCell]] = [[] for _ in _LABELS]

    def cell(e: Any, *, to_weekend: bool = False, weekend: bool = False):
        return HomeworkCell(
            subject=e.subject,
            description=e.description,
            deadline=e.deadline,
            dimmed=e.deadline < today,
            due_today=e.deadline == today,
            to_weekend=to_weekend,
            is_weekend_copy=weekend,
        )

    def index(d: date) -> int:
        return min((d - start).days, _WEEKEND)

    for e in entries:
        later = e.deadline > end
        if start <= e.registered_on <= end:
            idx = index(e.registered_on)
            if idx == _WEEKEND:
                buckets[idx].append(cell(e, weekend=True))
            else:
                buckets[idx].append(cell(e, to_weekend=later))
                if later:
                    buckets[_WEEKEND].append(cell(e, weekend=True))
        elif e.registered_on < start:
            if start <= e.deadline <= end:
                idx = index(e.deadline)
                buckets[idx].append(cell(e, weekend=idx == _WEEKEND))
            elif later:
                buckets[_WEEKEND].append(cell(e, weekend=True))

    today_idx = index(today) if start <= today <= end else None
    columns = [
        WeekColumn(
            label=label,
            day=start + timedelta(days=i) if i < _WEEKEND else None,
            is_today=i == today_idx,
            cells=sorted(buckets[i], key=lambda c: c.subject),
        )
        for i, label in enumerate(_LABELS)
    ]
    return HomeworkWeek(columns=columns)
