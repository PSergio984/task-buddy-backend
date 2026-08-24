"""Offline smoke checks over the breakdown golden set (no LLM).

The golden set is primarily a MANUAL harness (re-run samples through the live
endpoint after any prompt/model change and eyeball the result — see the file
header). These tests only assert what can be checked offline: every sample
prompt-builds cleanly within limits, and frozen parser cases keep their
recorded behavior.
"""

import json
from pathlib import Path

from app.knowledge.breakdown import (
    INPUT_CHAR_LIMIT,
    build_breakdown_prompt,
    parse_proposal,
)

GOLDEN_PATH = Path(__file__).parent / "golden" / "breakdown_golden.json"


def _samples() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["samples"]


def test_golden_file_loads_with_expected_categories() -> None:
    categories = {s["category"] for s in _samples()}
    assert {
        "single_task",
        "multi_task_blob",
        "non_task",
        "large_input",
        "parser_regression",
    } <= categories
    assert len(_samples()) >= 12


def test_every_sample_prompt_builds_within_limits() -> None:
    for sample in _samples():
        prompt = build_breakdown_prompt(
            sample["input"],
            context_title=sample.get("context_title"),
            context_description=sample.get("context_description"),
        )
        assert len(prompt) < INPUT_CHAR_LIMIT * 2, sample["id"]
        # input text itself must survive clamping without truncation
        assert len(sample["input"]) <= INPUT_CHAR_LIMIT or sample["category"] == "large_input"


def test_frozen_parser_cases() -> None:
    frozen = [s for s in _samples() if "frozen_output" in s]
    assert len(frozen) == 3

    happy = parse_proposal(frozen[0]["frozen_output"])
    assert happy.reason is None
    assert happy.tasks[0].title == "Set up CI"
    assert happy.tasks[0].estimated_effort_minutes == 45

    empty = parse_proposal(frozen[1]["frozen_output"])
    assert empty.tasks == []
    assert empty.reason is None

    garbage = parse_proposal(frozen[2]["frozen_output"])
    assert garbage.tasks == []
    assert garbage.reason is not None
