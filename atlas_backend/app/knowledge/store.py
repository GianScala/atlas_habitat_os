"""Uploaded documents: saving them, indexing them, and listing them.

The file is written under KNOWLEDGE_DIR so it can be re-read or handed back, and
its passages go into SQLite alongside everything else ATLAS remembers. Both
stay on this machine.

CONNECTING is separate from uploading on purpose. A document sitting in the
store is inert; only a connected one is searched, and disconnecting is instant
and reversible. That distinction is what makes it safe to keep a draft procedure
around without the assistant quoting it as current.
"""

import json
import time
import uuid
from pathlib import Path

from app.config import get_settings
from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.knowledge import chunk as chunker
from app.knowledge import embed as embedder
from app.knowledge import extract
from app.storage.database import connect

log = get_logger(__name__)


def _directory() -> Path:
    path = get_settings().resolved_knowledge_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def add(filename: str, data: bytes, note: str = "") -> dict:
    """Save, extract, chunk, index, and connect one document.

    Indexing happens here rather than lazily so the interface can report what
    happened while somebody is still looking at it: how many passages, and
    whether they were embedded or indexed lexically.
    """
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise AtlasError(
            f"{filename} is {len(data) / 1_048_576:.1f} MB, over the "
            f"{settings.max_upload_mb} MB limit."
        )
    if not data:
        raise AtlasError(f"{filename} is empty.")

    text = extract.extract(filename, data)
    passages = chunker.split(text)
    if not passages:
        raise AtlasError(f"{filename} produced no searchable text.")

    vectors = embedder.embed(passages)
    indexing = embedder.VECTOR if vectors else embedder.LEXICAL

    document_id = uuid.uuid4().hex[:12]
    suffix = Path(filename).suffix.lower()
    stored = _directory() / f"{document_id}{suffix}"
    stored.write_bytes(data)

    now = time.time()
    with connect() as connection:
        connection.execute(
            "INSERT INTO knowledge_documents (id, filename, kind, bytes, "
            "characters, chunks, indexing, connected, note, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                document_id,
                filename,
                extract.SUPPORTED.get(suffix, "document"),
                len(data),
                len(text),
                len(passages),
                indexing,
                note.strip()[:500],
                now,
            ),
        )
        connection.executemany(
            "INSERT INTO knowledge_chunks (document_id, ordinal, text, embedding) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    document_id,
                    ordinal,
                    passage,
                    json.dumps(vectors[ordinal]) if vectors else None,
                )
                for ordinal, passage in enumerate(passages)
            ],
        )

    log.info(
        "Knowledge: added %s (%d passages, %s indexing)",
        filename,
        len(passages),
        indexing,
    )
    return get(document_id)


def documents(connected_only: bool = False) -> list[dict]:
    """Every document in the store, newest first."""
    clause = "WHERE connected = 1 " if connected_only else ""
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, filename, kind, bytes, characters, chunks, indexing, "
            f"connected, note, uploaded_at FROM knowledge_documents {clause}"
            "ORDER BY uploaded_at DESC"
        ).fetchall()
    return [_as_dict(row) for row in rows]


def get(document_id: str) -> dict:
    with connect() as connection:
        row = connection.execute(
            "SELECT id, filename, kind, bytes, characters, chunks, indexing, "
            "connected, note, uploaded_at FROM knowledge_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise AtlasError(f"No document with id {document_id!r}.", status_code=404)
    return _as_dict(row)


def set_connected(document_id: str, connected: bool) -> dict:
    """Attach or detach one document from the assistant."""
    get(document_id)  # 404s if it is not there
    with connect() as connection:
        connection.execute(
            "UPDATE knowledge_documents SET connected = ? WHERE id = ?",
            (1 if connected else 0, document_id),
        )
    return get(document_id)


def remove(document_id: str) -> None:
    """Forget a document entirely, passages and file included."""
    document = get(document_id)
    with connect() as connection:
        connection.execute(
            "DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,)
        )
        connection.execute(
            "DELETE FROM knowledge_documents WHERE id = ?", (document_id,)
        )

    suffix = Path(document["filename"]).suffix.lower()
    stored = _directory() / f"{document_id}{suffix}"
    try:
        stored.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - the row is already gone
        log.warning("Could not delete %s: %s", stored, exc)


def passages(document_ids: list[str] | None = None) -> list[dict]:
    """Every indexed passage of the given documents, or of the connected ones."""
    with connect() as connection:
        if document_ids is None:
            rows = connection.execute(
                "SELECT c.document_id, c.ordinal, c.text, c.embedding, d.filename "
                "FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON d.id = c.document_id "
                "WHERE d.connected = 1"
            ).fetchall()
        elif not document_ids:
            return []
        else:
            marks = ", ".join("?" for _ in document_ids)
            rows = connection.execute(
                "SELECT c.document_id, c.ordinal, c.text, c.embedding, d.filename "
                "FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON d.id = c.document_id "
                f"WHERE c.document_id IN ({marks})",
                document_ids,
            ).fetchall()

    return [
        {
            "document_id": row["document_id"],
            "filename": row["filename"],
            "ordinal": row["ordinal"],
            "text": row["text"],
            "embedding": json.loads(row["embedding"]) if row["embedding"] else None,
        }
        for row in rows
    ]


def connected_count() -> int:
    """How many documents the assistant may currently search."""
    try:
        with connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM knowledge_documents WHERE connected = 1"
            ).fetchone()
        return int(row["n"]) if row else 0
    except Exception as exc:  # pragma: no cover - a feature, not a rule
        log.warning("Could not count connected documents: %s", exc)
        return 0


def _as_dict(row) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "kind": row["kind"],
        "bytes": row["bytes"],
        "characters": row["characters"],
        "chunks": row["chunks"],
        "indexing": row["indexing"],
        "connected": bool(row["connected"]),
        "note": row["note"],
        "uploaded_at": row["uploaded_at"],
    }
