"""Turning passages into vectors, on this machine.

Embeddings come from Ollama, which is already how ATLAS runs a model locally,
so a habitat's procedures never leave it to be indexed. The model is small
(`nomic-embed-text` is ~270 MB) and is pulled the same way any other is.

WHEN THERE IS NO EMBEDDING MODEL the knowledge base still works. Retrieval falls
back to lexical scoring, which is worse at synonyms and fine at the thing these
documents are mostly asked for: a named procedure, a number, a call sign. A
feature that silently does nothing would be worse than one that is honestly
described as degraded, so the interface says which mode is in force.
"""

import math
import re

import requests

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# How a passage was indexed. Stored per chunk so a document embedded before the
# model was installed is not silently mixed with one embedded after.
VECTOR = "vector"
LEXICAL = "lexical"

_WORD = re.compile(r"[a-z0-9]+")

# Words too common to distinguish one passage from another.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have how i if in into is it its
    of on or that the their then there these they this to was were what when
    where which who will with you your""".split()
)


def available() -> tuple[bool, str]:
    """(is an embedding model ready, a sentence saying why not).

    Checked against the running Ollama rather than assumed, because the model
    is an optional pull and the answer changes the moment someone installs it.
    """
    settings = get_settings()
    if not settings.embedding_model:
        return False, "No embedding model configured (EMBEDDING_MODEL)."

    try:
        response = requests.get(f"{settings.ollama_base}/api/tags", timeout=5)
        response.raise_for_status()
        installed = {
            model.get("name", "") for model in response.json().get("models", [])
        }
    except requests.RequestException as exc:
        return False, f"Ollama is not reachable ({exc.__class__.__name__})."

    wanted = settings.embedding_model
    if wanted in installed or f"{wanted}:latest" in installed:
        return True, ""
    return False, (
        f"The embedding model {wanted} is not installed. Run: ollama pull {wanted}"
    )


def embed(texts: list[str]) -> list[list[float]] | None:
    """Vectors for these passages, or None if no model could produce them.

    None is a normal outcome, not a failure: the caller indexes lexically
    instead and says so.
    """
    if not texts:
        return []

    ready, reason = available()
    if not ready:
        log.info("Indexing without embeddings: %s", reason)
        return None

    settings = get_settings()
    vectors: list[list[float]] = []
    for text in texts:
        try:
            response = requests.post(
                f"{settings.ollama_base}/api/embeddings",
                json={"model": settings.embedding_model, "prompt": text},
                timeout=settings.ollama_timeout,
            )
            response.raise_for_status()
            vector = response.json().get("embedding")
        except (requests.RequestException, ValueError) as exc:
            log.warning("Embedding failed, falling back to lexical: %s", exc)
            return None
        if not vector:
            return None
        vectors.append([float(value) for value in vector])
    return vectors


def embed_one(text: str) -> list[float] | None:
    vectors = embed([text])
    return vectors[0] if vectors else None


def cosine(left: list[float], right: list[float]) -> float:
    """Similarity of two vectors, 0 when either has no magnitude."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def tokenise(text: str) -> list[str]:
    """The words a lexical match scores on."""
    return [
        word
        for word in _WORD.findall(text.lower())
        if len(word) > 1 and word not in _STOPWORDS
    ]


def lexical_score(query_terms: list[str], passage: str) -> float:
    """How well a passage answers a query, by shared words.

    Overlap weighted by how much of the query is covered, with a small bonus for
    a term appearing more than once. Crude, and enough to find "the emergency
    number for the medical lead" in a contact sheet.
    """
    if not query_terms:
        return 0.0
    words = tokenise(passage)
    if not words:
        return 0.0

    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1

    matched = 0
    weight = 0.0
    for term in set(query_terms):
        hits = counts.get(term, 0)
        if hits:
            matched += 1
            weight += 1 + math.log(hits)

    if not matched:
        return 0.0
    coverage = matched / len(set(query_terms))
    return coverage * (weight / (weight + 4))
