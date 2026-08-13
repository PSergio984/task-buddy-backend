"""Retrieval evaluation harness: precision@k / recall@k / F1.

Port of rag-search-engine's evaluation_cli.py math, embedded in pytest.
The search function is injected so the harness is testable standalone and
against any search implementation (T-7-10: math locked by unit tests).
"""

import json
from pathlib import Path
from typing import Callable

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "golden_knowledge.json"
)

SearchFn = Callable[[str, int], list[int]]


def precision_at_k(retrieved_ids: list[int], relevant_ids: set[int], k: int) -> float:
    """Precision@k: fraction of the top-k retrieved ids that are relevant."""
    if k <= 0:
        return 0.0
    hits = sum(1 for i in retrieved_ids[:k] if i in relevant_ids)
    return hits / k


def recall_at_k(retrieved_ids: list[int], relevant_ids: set[int], k: int) -> float:
    """Recall@k: fraction of relevant ids captured in the top-k."""
    if not relevant_ids:
        return 0.0
    hits = sum(1 for i in retrieved_ids[:k] if i in relevant_ids)
    return hits / len(relevant_ids)


def f1_at_k(retrieved_ids: list[int], relevant_ids: set[int], k: int) -> float:
    """F1@k: harmonic mean of precision@k and recall@k."""
    p = precision_at_k(retrieved_ids, relevant_ids, k)
    r = recall_at_k(retrieved_ids, relevant_ids, k)
    if p + r <= 0:
        return 0.0
    return 2 * (p * r) / (p + r)


def evaluate_search(
    search_fn: SearchFn,
    dataset: dict,
    ks: tuple[int, ...] = (3, 5),
) -> dict:
    """Run the golden dataset through search_fn and macro-average P/R/F1 per k."""
    per_case: list[dict] = []
    for case in dataset["test_cases"]:
        retrieved = search_fn(case["task_query"], max(ks))
        relevant = set(case["relevant_knowledge_ids"])
        per_case.append(
            {
                "task_id": case["task_id"],
                "retrieved": retrieved,
                "relevant": sorted(relevant),
                "scores": {f"precision@{k}": precision_at_k(retrieved, relevant, k) for k in ks}
                | {f"recall@{k}": recall_at_k(retrieved, relevant, k) for k in ks}
                | {f"f1@{k}": f1_at_k(retrieved, relevant, k) for k in ks},
            }
        )

    macro: dict[str, float] = {}
    case_count = len(per_case)
    for k in ks:
        for metric in ("precision", "recall", "f1"):
            key = f"{metric}@{k}"
            macro[key] = sum(c["scores"][key] for c in per_case) / case_count if case_count else 0.0

    return {"per_case": per_case, "macro": macro}


def load_golden_dataset(path: str | Path = DEFAULT_DATASET_PATH) -> dict:
    """Load and schema-validate the golden dataset fixture."""
    with Path(path).open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or "test_cases" not in data:
        raise ValueError("golden dataset must contain a 'test_cases' list")

    for case in data["test_cases"]:
        required = {"task_id", "task_query", "task_title", "notes", "relevant_knowledge_ids"}
        missing = required - set(case.keys())
        if missing:
            raise ValueError(f"case {case.get('task_id')} missing keys: {sorted(missing)}")
        note_ids = {n["knowledge_id"] for n in case["notes"]}
        if not set(case["relevant_knowledge_ids"]) <= note_ids:
            raise ValueError(
                f"case {case['task_id']} has relevant ids not in its notes: "
                f"{set(case['relevant_knowledge_ids']) - note_ids}"
            )
    return data
