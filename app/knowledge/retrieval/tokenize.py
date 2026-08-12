"""Text tokenization for retrieval: punctuation strip, stopword filter, Porter stem."""

import string
from pathlib import Path

from nltk.stem import PorterStemmer

_STOPWORDS_PATH = Path(__file__).resolve().parent / "stopwords.txt"


def _load_stopwords() -> frozenset[str]:
    with _STOPWORDS_PATH.open("r", encoding="utf-8") as f:
        return frozenset(_preprocess(word) for word in f.read().splitlines() if word)


def _preprocess(text: str) -> str:
    """Lowercase and delete all punctuation (contractions become 'arent')."""
    return text.lower().translate(str.maketrans("", "", string.punctuation))


STOPWORDS: frozenset[str] = _load_stopwords()


def tokenize_text(text: str) -> list[str]:
    """Full preprocessing: lowercase, strip punctuation, split, drop stopwords, stem."""
    tokens = _preprocess(text).split()
    valid_tokens = [t for t in tokens if t and t not in STOPWORDS]
    stemmer = PorterStemmer()
    return [stemmer.stem(t) for t in valid_tokens]
