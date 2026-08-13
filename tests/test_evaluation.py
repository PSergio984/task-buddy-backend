"""Tests for the evaluation harness (P@k/R@k/F1) and golden dataset gates."""

import pytest

from app.knowledge.evaluation import (
    evaluate_search,
    f1_at_k,
    load_golden_dataset,
    precision_at_k,
    recall_at_k,
)


def test_precision_recall_f1_math() -> None:
    retrieved = [1, 2, 3, 4, 5]
    relevant = {2, 5, 9}
    assert precision_at_k(retrieved, relevant, 3) == 1 / 3
    assert recall_at_k(retrieved, relevant, 3) == 1 / 3
    # F1 = 2pr/(p+r) = 2*(1/9)/(2/3) = 1/3
    assert f1_at_k(retrieved, relevant, 3) == 1 / 3


def test_precision_zero_when_limit_zero() -> None:
    assert precision_at_k([1, 2, 3], {1}, 0) == 0.0


def test_f1_zero_when_no_overlap() -> None:
    assert f1_at_k([1, 2, 3], {9, 10}, 3) == 0.0


def test_golden_dataset_schema_valid() -> None:
    dataset = load_golden_dataset()
    assert isinstance(dataset["test_cases"], list)


def test_golden_dataset_has_10_to_20_cases() -> None:
    dataset = load_golden_dataset()
    assert 10 <= len(dataset["test_cases"]) <= 20


def test_golden_dataset_ids_resolve_to_notes() -> None:
    dataset = load_golden_dataset()
    for case in dataset["test_cases"]:
        note_ids = {n["knowledge_id"] for n in case["notes"]}
        assert set(case["relevant_knowledge_ids"]) <= note_ids


def test_evaluate_search_macro_averages() -> None:
    dataset = {
        "test_cases": [
            {
                "task_id": 1,
                "task_query": "q1",
                "task_title": "t1",
                "notes": [{"knowledge_id": 10, "content": "a"}],
                "relevant_knowledge_ids": [10],
            },
            {
                "task_id": 2,
                "task_query": "q2",
                "task_title": "t2",
                "notes": [{"knowledge_id": 20, "content": "b"}],
                "relevant_knowledge_ids": [20],
            },
        ]
    }

    def fake_search(query: str, limit: int) -> list[int]:
        return [10, 99, 98]  # case 1 hits at rank 1; case 2 misses entirely

    result = evaluate_search(fake_search, dataset, ks=(3, 5))
    macro = result["macro"]
    # Case 1: p@3 = 1/3, r@3 = 1, f1@3 = 0.5. Case 2: all zeros.
    assert macro["precision@3"] == pytest.approx(1 / 6)
    assert macro["recall@3"] == pytest.approx(0.5)
    assert macro["f1@3"] == pytest.approx(0.25)
