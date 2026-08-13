"""BM25 inverted index — port of rag-search-engine's keyword_search_cli.

Deltas from the source engine: per-user instances, incremental add/remove
lifecycle, and a content hash for cache invalidation. Doc ids are knowledge
chunk ids.
"""

import math
from collections import Counter, defaultdict
from typing import Optional

from app.knowledge.retrieval.tokenize import tokenize_text

BM25_K1 = 1.5
BM25_B = 0.75


class InvertedIndex:
    """Per-user BM25 index over knowledge chunk texts."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.index: defaultdict[str, set[int]] = defaultdict(set)
        self.docmap: dict[int, dict] = {}
        self.term_frequencies: dict[int, Counter] = {}
        self._avg_doc_len: Optional[float] = None

    def add_document(self, doc_id: int, text: str, metadata: Optional[dict] = None) -> None:
        """Incrementally add (or replace) a document's tokens to the index."""
        tokens = tokenize_text(text)
        self.remove_document(doc_id)

        for token in set(tokens):
            self.index[token].add(doc_id)
        self.term_frequencies[doc_id] = Counter(tokens)
        self.docmap[doc_id] = metadata or {}
        self._avg_doc_len = None

    def remove_document(self, doc_id: int) -> None:
        """Remove a document from the index, if present."""
        tf = self.term_frequencies.pop(doc_id, None)
        if tf is not None:
            for token in tf:
                self.index[token].discard(doc_id)
                if not self.index[token]:
                    del self.index[token]
        self.docmap.pop(doc_id, None)
        self._avg_doc_len = None

    def get_documents(self, term: str) -> list[int]:
        """Return document ids for a single preprocessed token, sorted ascending."""
        return sorted(self.index.get(term, set()))

    def get_bm25_idf(self, term: str) -> float:
        """BM25 IDF with Laplace smoothing (always positive)."""
        n = len(self.docmap)
        df = len(self.index.get(term, set()))
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def get_bm25_tf(self, doc_id: int, term: str, k1: float = BM25_K1) -> float:
        """BM25 term frequency with saturation + document length normalization."""
        tf = self.get_tf(doc_id, term)
        doc_counter = self.term_frequencies.get(doc_id)
        doc_len = sum(doc_counter.values()) if doc_counter else 0

        if self._avg_doc_len is None:
            if self.term_frequencies:
                total = sum(sum(c.values()) for c in self.term_frequencies.values())
                # Tokenless documents (all stopwords) yield avg 0 — fall back
                # to 1.0 to keep the saturation ratio defined.
                self._avg_doc_len = total / len(self.term_frequencies) or 1.0
            else:
                self._avg_doc_len = 1.0

        ratio = doc_len / self._avg_doc_len
        k = k1 * (1 - BM25_B + BM25_B * ratio)
        return (tf * (k1 + 1)) / (tf + k)

    def bm25(self, doc_id: int, term: str) -> float:
        """Full BM25 score for a term in a document: tf * idf."""
        return self.get_bm25_tf(doc_id, term) * self.get_bm25_idf(term)

    def bm25_search(self, query: str, limit: int = 10) -> list[tuple[int, float]]:
        """Rank all documents by summed BM25 score for the query tokens."""
        query_tokens = tokenize_text(query)
        if not query_tokens:
            return []

        scores: dict[int, float] = {}
        for doc_id in self.docmap:
            total = sum(self.bm25(doc_id, token) for token in query_tokens)
            if total > 0:
                scores[doc_id] = total

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:limit]

    def get_tf(self, doc_id: int, term: str) -> int:
        """Return how many times the token appears in the document."""
        doc_counter = self.term_frequencies.get(doc_id)
        if not doc_counter:
            return 0
        return doc_counter.get(term, 0)
