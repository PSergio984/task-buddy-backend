"""Availability-source boundary: connector protocol + synthetic implementation.

Stateless, no DB. Mirrors the Phase 7 Source-protocol shape structurally
(D-09); the protocol is the swap point for a future real calendar connector.
"""

import logging
from datetime import date, datetime, time, timezone
from typing import Protocol

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class CalendarEvent(BaseModel):
    """A named calendar event (D-10 shape); aware UTC datetimes."""

    model_config = ConfigDict(frozen=True)

    title: str
    start: datetime
    end: datetime


class CalendarConnector(Protocol):
    """Availability-source boundary: one method, per-user scoped by contract."""

    def events_for(self, user_id: int, date: date) -> list[CalendarEvent]:
        """Return the user's events on the given date."""
        ...


class SyntheticCalendarConnector:
    """Fixed demo dataset (D-11): Wednesday 18:00-19:00 sync + 20:30-21:00 block.

    Deterministic and user-independent; gated at the call site by
    SYNTHETIC_CALENDAR_ENABLED. 240 - 60 - 30 = 150 min free = the
    "2.5h free tonight" demo narrative (09-CONTEXT.md D-12).
    """

    def events_for(self, user_id: int, date: date) -> list[CalendarEvent]:
        if date.weekday() != 2:  # Wednesday only
            return []
        return [
            CalendarEvent(
                title="Weekly team sync",
                start=datetime.combine(date, time(18, 0), tzinfo=timezone.utc),
                end=datetime.combine(date, time(19, 0), tzinfo=timezone.utc),
            ),
            CalendarEvent(
                title="Personal block",
                start=datetime.combine(date, time(20, 30), tzinfo=timezone.utc),
                end=datetime.combine(date, time(21, 0), tzinfo=timezone.utc),
            ),
        ]


def available_minutes(
    events: list[CalendarEvent],
    working_window: tuple[int, int] = (18, 22),
) -> int:
    """Free minutes in the working window after subtracting (unioned) events.

    Malformed events (start >= end) and events entirely outside the window
    are skipped; straddling events are clipped; overlapping events are
    unioned. Never returns a negative value.
    """
    start_hour, end_hour = working_window
    if end_hour <= start_hour:
        return 0
    total = (end_hour - start_hour) * 60

    intervals: list[tuple[float, float]] = []
    for event in events:
        if event.start >= event.end:
            logger.warning("skipping malformed calendar event: %s", event.title)
            continue
        start_ts = event.start.timestamp()
        end_ts = event.end.timestamp()
        window_start = datetime.combine(
            event.start.date(), time(start_hour), tzinfo=event.start.tzinfo
        ).timestamp()
        window_end = datetime.combine(
            event.start.date(), time(end_hour), tzinfo=event.start.tzinfo
        ).timestamp()
        clipped_start = max(start_ts, window_start)
        clipped_end = min(end_ts, window_end)
        if clipped_end <= clipped_start:
            continue  # entirely outside the window
        intervals.append((clipped_start, clipped_end))

    intervals.sort()
    covered: float = 0
    current_end: float | None = None
    for start_ts, end_ts in intervals:
        if current_end is None or start_ts > current_end:
            covered += end_ts - start_ts
            current_end = end_ts
        elif end_ts > current_end:
            covered += end_ts - current_end
            current_end = end_ts

    return max(0, total - round(covered / 60))
