"""Unit tests for the breakdown proposal service (pure logic, no LLM)."""

import pytest
from pydantic import ValidationError

from app.knowledge.breakdown import (
    BREAKDOWN_SYSTEM_PROMPT,
    INPUT_CHAR_LIMIT,
    MAX_SUBTASKS_PER_TASK,
    MAX_TASKS_PER_PROPOSAL,
    BreakdownTaskProposal,
    build_breakdown_prompt,
    parse_proposal,
)


class TestPromptBuilder:
    def test_includes_text_and_rules(self) -> None:
        prompt = build_breakdown_prompt("fix the login bug")
        assert "fix the login bug" in prompt
        assert BREAKDOWN_SYSTEM_PROMPT  # non-empty system prompt

    def test_long_input_clamped_to_limit(self) -> None:
        prompt = build_breakdown_prompt("x" * (INPUT_CHAR_LIMIT + 1000))
        assert len(prompt) < len("x" * (INPUT_CHAR_LIMIT + 1000))

    def test_context_task_section(self) -> None:
        prompt = build_breakdown_prompt(
            "clean up", context_title="Refactor auth", context_description="split work"
        )
        assert "Refactor auth" in prompt
        assert "split work" in prompt

    def test_memory_hints_rendered_when_present(self) -> None:
        prompt = build_breakdown_prompt("plan sprint", memory_hints=["Write docs", "Ship v1"])
        assert "Write docs" in prompt
        assert "Ship v1" in prompt

    def test_no_empty_hints_block(self) -> None:
        prompt = build_breakdown_prompt("plan sprint", memory_hints=[])
        assert "Similar past tasks" not in prompt

    def test_focus_task_rendered(self) -> None:
        prompt = build_breakdown_prompt("blob of tasks", focus_task_title="Deploy")
        assert "<focus>Deploy</focus>" in prompt

    def test_focus_number_and_title_rendered(self) -> None:
        prompt = build_breakdown_prompt(
            "blob of tasks",
            focus_task_title="Deploy",
            focus_task_number=2,
        )
        assert "<focus>#2 Deploy</focus>" in prompt
        # number-stable targeting must survive an emptied/edited title
        prompt_empty = build_breakdown_prompt(
            "blob", focus_task_number=3, focus_task_title=""
        )
        assert "<focus>#3</focus>" in prompt_empty

    def test_focus_number_alone_suffices(self) -> None:
        prompt = build_breakdown_prompt("blob", focus_task_number=5)
        assert "<focus>#5</focus>" in prompt


class TestParseDegrade:
    def test_valid_payload(self) -> None:
        payload = (
            '{"tasks": [{"title": "A", "estimated_effort_minutes": 30, '
            '"subtasks": [{"title": "a1"}, {"title": "a2"}]}]}'
        )
        proposal = parse_proposal(payload)
        assert proposal is not None
        assert proposal.reason is None
        assert [t.title for t in proposal.tasks] == ["A"]
        assert proposal.tasks[0].estimated_effort_minutes == 30
        assert [s.title for s in proposal.tasks[0].subtasks] == ["a1", "a2"]

    def test_invalid_json_degrades_never_raises(self) -> None:
        proposal = parse_proposal("not json at all {{{")
        assert proposal is not None
        assert proposal.tasks == []
        assert proposal.reason is not None

    def test_wrong_shape_degrades(self) -> None:
        proposal = parse_proposal('{"buckets": []}')
        assert proposal is not None
        assert proposal.tasks == []
        assert proposal.reason is not None

    def test_caps_tasks(self) -> None:
        tasks = ",".join(f'{{"title": "T{i}", "subtasks": []}}' for i in range(40))
        proposal = parse_proposal(f'{{"tasks": [{tasks}]}}')
        assert proposal is not None
        assert len(proposal.tasks) == MAX_TASKS_PER_PROPOSAL

    def test_caps_subtasks_per_task(self) -> None:
        subs = ",".join(f'{{"title": "s{i}"}}' for i in range(20))
        payload = f'{{"tasks": [{{"title": "A", "subtasks": [{subs}]}}]}}'
        proposal = parse_proposal(payload)
        assert proposal is not None
        assert len(proposal.tasks[0].subtasks) <= MAX_SUBTASKS_PER_TASK

    def test_blank_titles_dropped(self) -> None:
        payload = (
            '{"tasks": [{"title": "", "subtasks": []}, {"title": "Keep", "subtasks": []}]}'
        )
        proposal = parse_proposal(payload)
        assert proposal is not None
        assert [t.title for t in proposal.tasks] == ["Keep"]

    def test_effort_clamped_to_task_column_range(self) -> None:
        payload = (
            '{"tasks": [{"title": "A", "estimated_effort_minutes": 9999999, "subtasks": []}]}'
        )
        proposal = parse_proposal(payload)
        assert proposal is not None
        assert proposal.tasks[0].estimated_effort_minutes is None  # out of range dropped

    def test_effort_none_allowed(self) -> None:
        payload = '{"tasks": [{"title": "A", "subtasks": []}]}'
        proposal = parse_proposal(payload)
        assert proposal is not None
        assert proposal.tasks[0].estimated_effort_minutes is None


class TestSchemas:
    def test_subtask_rejects_nested_garbage(self) -> None:
        with pytest.raises(ValidationError):
            BreakdownTaskProposal.model_validate(
                {"title": "A", "subtasks": [{"nope": True}], "extra": 1}
            )
