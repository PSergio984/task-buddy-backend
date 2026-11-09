"""Unit tests for the import-extraction parser (`parse_proposals`).

The endpoint tests in `test_import_extract.py` cover the HTTP contract;
these pin the defensive-parse rules against odd or crafted provider output —
the caps, the type coercion, and the owned-ids grounding for
`suggested_project_id` — since the model's JSON is untrusted input.
"""

import json
from datetime import timedelta, timezone
from typing import Any

from app.knowledge.import_extract import (
    MAX_PROPOSALS,
    MAX_SUBTASKS_PER_PROPOSAL,
    parse_proposals,
)
from app.models.task import TaskPriority


def _item(**overrides: Any) -> dict[str, Any]:
    """A minimal valid raw proposal dict; keyword overrides per case."""
    item: dict[str, Any] = {
        "title": "Do the thing",
        "description": None,
        "proposed_deadline": None,
        "priority": "MEDIUM",
        "suggested_project_id": None,
        "subtasks": [],
    }
    item.update(overrides)
    return item


def _payload(items: list[Any]) -> str:
    return json.dumps({"proposals": items})


def test_parse_proposals_caps_at_max() -> None:
    items = [_item(title=f"task {i}") for i in range(MAX_PROPOSALS + 5)]
    extraction = parse_proposals(_payload(items), set())
    assert MAX_PROPOSALS == 15
    assert len(extraction.proposals) == MAX_PROPOSALS
    assert extraction.reason is None


def test_parse_proposals_caps_subtasks() -> None:
    item = _item(subtasks=[{"title": f"sub {i}"} for i in range(MAX_SUBTASKS_PER_PROPOSAL + 3)])
    extraction = parse_proposals(_payload([item]), set())
    assert MAX_SUBTASKS_PER_PROPOSAL == 7
    assert len(extraction.proposals) == 1
    assert len(extraction.proposals[0].subtasks) == MAX_SUBTASKS_PER_PROPOSAL


def test_parse_proposals_skips_non_dict_and_titleless_items() -> None:
    """Junk mid-list is skipped; surviving proposals keep list order."""
    items = [
        _item(title="first"),
        "junk",
        42,
        {"description": "dict without a title"},
        _item(title="second"),
        None,
    ]
    extraction = parse_proposals(_payload(items), set())
    assert [p.title for p in extraction.proposals] == ["first", "second"]
    assert extraction.reason is None


def test_parse_proposals_bad_envelope_degrades_with_reason() -> None:
    """A non-list `proposals` (or non-JSON) yields empty + reason, never raises."""
    for bad in (
        '{"proposals": "nope"}',
        '{"proposals": {"a": 1}}',
        "42",
        "not json",
    ):
        extraction = parse_proposals(bad, set())
        assert extraction.proposals == []
        assert extraction.reason is not None


def test_parse_proposals_project_id_coercion_rules() -> None:
    """Only int/str ids coerce; bools and floats never do — even when the
    coerced value would land inside the owned-ids set (1, 3 are owned)."""
    owned = {1, 3, 42}
    items = [
        _item(title="bool", suggested_project_id=True),  # int() would give 1
        _item(title="float", suggested_project_id=3.9),  # int() would give 3
        _item(title="str-id", suggested_project_id="42"),
        _item(title="int-id", suggested_project_id=42),
        _item(title="str-junk", suggested_project_id="abc"),
        _item(title="inf", suggested_project_id=float("inf")),  # int() would raise OverflowError
        _item(title="null", suggested_project_id=None),
        _item(title="foreign", suggested_project_id=999),
    ]
    extraction = parse_proposals(_payload(items), owned)
    by_title = {p.title: p.suggested_project_id for p in extraction.proposals}
    assert by_title == {
        "bool": None,
        "float": None,
        "str-id": 42,
        "int-id": 42,
        "str-junk": None,
        "inf": None,
        "null": None,
        "foreign": None,
    }


def test_parse_proposals_priority_parsing() -> None:
    """Case/whitespace-tolerant match to the enum; anything else -> MEDIUM."""
    items = [
        _item(title="padded", priority=" high"),
        _item(title="lower", priority="low"),
        _item(title="bogus", priority="URGENT"),
        _item(title="none", priority=None),
    ]
    extraction = parse_proposals(_payload(items), set())
    by_title = {p.title: p.priority for p in extraction.proposals}
    assert by_title == {
        "padded": TaskPriority.HIGH,
        "lower": TaskPriority.LOW,
        "bogus": TaskPriority.MEDIUM,
        "none": TaskPriority.MEDIUM,
    }


def test_parse_proposals_truncates_to_task_api_limits() -> None:
    """Over-limit titles/descriptions/subtasks are clipped at parse time so a
    long LLM title can't pass extraction and then 422 at task-create."""
    items = [
        _item(
            title="t" * 150,
            description="d" * 3000,
            subtasks=[{"title": "s" * 120}],
        )
    ]
    extraction = parse_proposals(_payload(items), set())
    proposal = extraction.proposals[0]
    assert len(proposal.title) == 100
    assert len(proposal.description) == 2000
    assert len(proposal.subtasks[0].title) == 80


def test_parse_proposals_deadline_parsing() -> None:
    """Naive ISO input anchors to UTC (never serialized offset-less); an
    explicit offset is preserved; unparseable drops to None."""
    items = [
        _item(title="naive", proposed_deadline="2026-09-01T10:00:00"),
        _item(title="offset", proposed_deadline="2026-09-01T10:00:00+02:00"),
        _item(title="garbage", proposed_deadline="next Friday"),
        _item(title="empty", proposed_deadline="   "),
    ]
    extraction = parse_proposals(_payload(items), set())
    by_title = {p.title: p.proposed_deadline for p in extraction.proposals}
    assert by_title["naive"].tzinfo == timezone.utc
    assert by_title["naive"].utcoffset() == timedelta(0)
    assert by_title["offset"].utcoffset() == timedelta(hours=2)
    assert by_title["garbage"] is None
    assert by_title["empty"] is None
