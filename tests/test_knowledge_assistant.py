"""Tests for the instrumented knowledge assistant (generate + judge + ask/feedback).

Wave 0 stubs: all tests are skipped until plan 07-04 wave 1 implements the
assistant/cost modules and the ask/feedback endpoints.
"""

import pytest


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_llm_call_record_fields() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_calculate_cost_pricing_map() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_generate_answer_returns_metrics() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_generate_answer_persists_answer_row() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_judge_verdict_labels_and_explanation() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_ask_endpoint_returns_answer_with_citations() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_ask_endpoint_rejects_foreign_task() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_feedback_rating_persists() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_feedback_rejects_foreign_answer() -> None:
    assert True


@pytest.mark.skip(reason="implemented in plan 04 wave 1")
def test_no_api_key_in_any_response() -> None:
    assert True
