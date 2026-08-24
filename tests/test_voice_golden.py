"""Offline smoke checks over the voice golden set (no STT/LLM calls).

The golden set is primarily a MANUAL harness (re-run each sample through a
live POST /api/v1/voice/plan after any STT/model change and eyeball the plan
against the spec §4 quality bar: ≥1 non-empty bucket, non-empty reasons, no
crash). These tests only assert what is checkable offline: every recorded
sample passes through the blank-transcript gate exactly as recorded.
"""

import json
from pathlib import Path

from app.knowledge.voice import is_blank_transcript

GOLDEN_PATH = Path(__file__).parent / "golden" / "voice_golden.json"


def _samples() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["samples"]


def test_golden_file_loads_with_expected_categories() -> None:
    categories = {s["category"] for s in _samples()}
    assert {
        "question",
        "task_dump",
        "numbers_and_times",
        "chatter",
        "taglish_best_effort",
        "very_long",
        "empty_ish",
    } <= categories
    assert len(_samples()) >= 8


def test_recorded_blank_flags_match_the_gate() -> None:
    for sample in _samples():
        assert is_blank_transcript(sample["transcript"]) == sample["blank"], sample["id"]
