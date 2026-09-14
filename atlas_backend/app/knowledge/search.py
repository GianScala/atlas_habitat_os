"""Finding the passages that answer a question.

Vector similarity where the passages were embedded, lexical overlap where they
were not, and both scored together when a store holds some of each. Whichever
was used is reported, because a lexical result is a weaker claim than a semantic
one and the answer should be able to say so.

WHAT THIS DOES NOT DO is decide anything. It returns passages and where they
came from; the model reads them and answers, under the same rule as every other
tool: quote what the source says, cite it, and do not fill gaps.
"""


from app.core.logging import get_logger
from app.knowledge import chunk as chunker
from app.knowledge import embed as embedder
from app.knowledge import store

log = get_logger(__name__)

# Below this, a passage is noise rather than a weak match. Returning everything
# ranked would hand the model a page of irrelevance and invite it to use some.
MIN_SCORE = 0.05


def search(query: str, limit: int = 6) -> dict:
    """The best passages from the connected documents for this question."""
    query = str(query or "").strip()
    if not query:
        raise ValueError("search_knowledge needs something to search for.")

    passages = store.passages()
    if not passages:
        return {
            "query": query,
            "data": None,
            "note": (
                "No documents are connected. Attach one under Settings, "
                "Connectors, and it becomes searchable."
            ),
        }

    query_vector = embedder.embed_one(query)
    terms = embedder.tokenise(query)

    scored: list[tuple[float, str, dict]] = []
    for passage in passages:
        vector = passage["embedding"]
        if query_vector and vector:
            score = embedder.cosine(query_vector, vector)
            how = embedder.VECTOR
        else:
            # Scored on the passage's own words, not the tail carried over
            # from the one before it.
            score = embedder.lexical_score(terms, chunker.core_text(passage["text"]))
            how = embedder.LEXICAL
        if score >= MIN_SCORE:
            scored.append((score, how, passage))

    scored.sort(key=lambda entry: entry[0], reverse=True)
    best = scored[: max(1, int(limit))]

    if not best:
        searched = len({p["document_id"] for p in passages})
        return {
            "query": query,
            "data": None,
            "searched_documents": searched,
            "note": (
                f"Searched {len(passages)} passages across {searched} connected "
                "document(s) and found nothing matching. Say what you searched "
                "rather than that the habitat has no such procedure."
            ),
        }

    modes = {how for _, how, _ in best}
    return {
        "query": query,
        "data": [
            {
                "document": passage["filename"],
                "passage": passage["ordinal"] + 1,
                "relevance": round(score, 4),
                "text": passage["text"],
            }
            for score, _, passage in best
        ],
        "matching": _how_note(modes),
        "note": (
            "These are passages from documents the crew attached, not telemetry. "
            "Quote what they say and name the document. If they do not answer the "
            "question, say so rather than filling the gap."
        ),
    }


def _how_note(modes: set[str]) -> str:
    if modes == {embedder.VECTOR}:
        return "Ranked by meaning (embeddings)."
    if modes == {embedder.LEXICAL}:
        return (
            "Ranked by shared words, not meaning, because these documents were "
            "indexed without an embedding model. A passage phrased differently "
            "from the question may have been missed."
        )
    return "Ranked by meaning where available, by shared words otherwise."


def search_knowledge(query: str, limit: int | None = None) -> dict:
    """The tool entry point. See `tools/schemas.py` for what the model is told."""
    from app.config import get_settings

    return search(query, limit or get_settings().knowledge_results)
