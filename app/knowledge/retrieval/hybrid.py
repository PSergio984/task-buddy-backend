"""Hybrid retrieval: BM25 + semantic fused via reciprocal rank fusion."""

from typing import Optional

RRF_K = 60


def rrf_search(
    bm25_results: list[tuple[int, float]],
    semantic_results: list[dict],
    k: int = RRF_K,
    limit: int = 10,
) -> list[dict]:
    """Fuse BM25 and semantic rankings via RRF: score = sum(1/(k + rank)) over the union.

    Ranks are 1-based positions within each system's result list.
    """
    bm25_ranks: dict[int, int] = {}
    for rank, (doc_id, _score) in enumerate(bm25_results, 1):
        bm25_ranks[doc_id] = rank

    sem_ranks: dict[int, int] = {}
    sem_texts: dict[int, str] = {}
    for rank, r in enumerate(semantic_results, 1):
        sem_ranks[r["chunk_id"]] = rank
        sem_texts[r["chunk_id"]] = r.get("text", "")

    all_ids = set(bm25_ranks.keys()) | set(sem_ranks.keys())

    combined: list[dict] = []
    for chunk_id in all_ids:
        bm25_rank: Optional[int] = bm25_ranks.get(chunk_id)
        sem_rank: Optional[int] = sem_ranks.get(chunk_id)

        rrf_score = 0.0
        if bm25_rank is not None:
            rrf_score += 1.0 / (k + bm25_rank)
        if sem_rank is not None:
            rrf_score += 1.0 / (k + sem_rank)

        combined.append(
            {
                "chunk_id": chunk_id,
                "rrf_score": rrf_score,
                "bm25_rank": bm25_rank,
                "semantic_rank": sem_rank,
                "text": sem_texts.get(chunk_id, ""),
            }
        )

    # Deterministic ordering: score desc, then chunk_id (set iteration order
    # would otherwise decide ties).
    combined.sort(key=lambda x: (-x["rrf_score"], x["chunk_id"]))
    return combined[:limit]
