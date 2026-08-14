"""Tests for the Phase 9 calendar connector (plan 09-03)."""

from datetime import date, datetime, time, timezone

from app.planner.connector import (
    CalendarEvent,
    SyntheticCalendarConnector,
    available_minutes,
)

WED = date(2026, 8, 19)  # a Wednesday


def mk_event(title: str, start_h: int, start_m: int, end_h: int, end_m: int) -> CalendarEvent:
    return CalendarEvent(
        title=title,
        start=datetime.combine(WED, time(start_h, start_m), tzinfo=timezone.utc),
        end=datetime.combine(WED, time(end_h, end_m), tzinfo=timezone.utc),
    )


def test_available_minutes_full_window_no_events() -> None:
    assert available_minutes([], (18, 22)) == 240
    assert available_minutes([], (0, 24)) == 1440


def test_available_minutes_subtracts_meeting() -> None:
    assert available_minutes([mk_event("m", 18, 0, 19, 0)], (18, 22)) == 180


def test_available_minutes_demo_dataset_150_minutes() -> None:
    events = [
        mk_event("Weekly team sync", 18, 0, 19, 0),
        mk_event("Personal block", 20, 30, 21, 0),
    ]
    assert available_minutes(events, (18, 22)) == 150


def test_available_minutes_ignores_out_of_window_events() -> None:
    assert available_minutes([mk_event("early", 9, 0, 10, 0)], (18, 22)) == 240
    # Straddles the start edge: 17:00-18:30 clipped to 18:00-18:30 = 30 covered.
    assert available_minutes([mk_event("straddle", 17, 0, 18, 30)], (18, 22)) == 210


def test_available_minutes_skips_malformed_events() -> None:
    assert available_minutes([mk_event("bad", 19, 0, 18, 0)], (18, 22)) == 240
    assert available_minutes([], (22, 18)) == 0


def test_available_minutes_unions_overlapping_events() -> None:
    events = [
        mk_event("a", 18, 0, 20, 0),
        mk_event("b", 19, 0, 21, 0),
    ]
    assert available_minutes(events, (18, 22)) == 60


def test_events_for_wednesday_returns_demo_dataset() -> None:
    connector = SyntheticCalendarConnector()
    events = connector.events_for(1, WED)
    assert len(events) == 2
    assert events[0].title == "Weekly team sync"
    assert events[0].start == datetime.combine(WED, time(18, 0), tzinfo=timezone.utc)
    assert events[0].end == datetime.combine(WED, time(19, 0), tzinfo=timezone.utc)
    assert events[1].title == "Personal block"
    assert events[1].start == datetime.combine(WED, time(20, 30), tzinfo=timezone.utc)
    assert events[1].end == datetime.combine(WED, time(21, 0), tzinfo=timezone.utc)
    for event in events:
        assert event.start.tzinfo == timezone.utc
        assert event.end.tzinfo == timezone.utc


def test_events_for_other_days_returns_empty() -> None:
    connector = SyntheticCalendarConnector()
    assert connector.events_for(1, date(2026, 8, 20)) == []  # Thursday


def test_events_for_is_deterministic_per_user() -> None:
    connector = SyntheticCalendarConnector()
    assert connector.events_for(1, WED) == connector.events_for(999, WED)
    assert connector.events_for(1, WED) == connector.events_for(1, WED)
