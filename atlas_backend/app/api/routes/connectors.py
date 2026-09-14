"""Connectors: the documents the assistant may read.

Upload a procedure, a contact sheet, a checklist. It is extracted, cut into
passages, indexed on this machine, and connected. From then on the assistant can
search it and cite it, alongside the telemetry it already reads.

Uploads and indexes are stored locally. Retrieved passages are sent to the
selected model, including a cloud provider when enabled.
"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.errors import AtlasError
from app.knowledge import embed, extract, store
from app.schemas.connectors import (
    ConnectorStatus,
    DocumentEntry,
    DocumentList,
    ToggleUpdate,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _refuse(exc: AtlasError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _listing() -> DocumentList:
    ready, reason = embed.available()
    settings = get_settings()
    documents = store.documents()
    return DocumentList(
        documents=[DocumentEntry(**entry) for entry in documents],
        status=ConnectorStatus(
            embeddings_ready=ready,
            embeddings_detail=reason,
            embedding_model=settings.embedding_model,
            accepts=extract.supported_note(),
            max_mb=settings.max_upload_mb,
            connected=sum(1 for entry in documents if entry["connected"]),
        ),
    )


@router.get("/documents", response_model=DocumentList)
def read_documents() -> DocumentList:
    """Everything in the knowledge base, and how it is being indexed."""
    try:
        return _listing()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.post("/documents", response_model=DocumentList)
async def upload_document(file: UploadFile = File(...)) -> DocumentList:
    """Add one document. It is indexed and connected immediately.

    Indexing is done here rather than in the background so the reply can say
    what happened while somebody is still looking at the page: how many
    passages, and whether they were embedded or matched on words.
    """
    try:
        limit = get_settings().max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(status_code=413, detail="Document exceeds upload limit.")
        await run_in_threadpool(store.add, file.filename or "document", data)
        return await run_in_threadpool(_listing)
    except AtlasError as exc:
        raise _refuse(exc) from exc
    finally:
        await file.close()


@router.put("/documents/{document_id}", response_model=DocumentList)
def toggle_document(document_id: str, body: ToggleUpdate) -> DocumentList:
    """Attach or detach one document. Disconnecting keeps it, unsearched."""
    try:
        store.set_connected(document_id, body.connected)
        return _listing()
    except AtlasError as exc:
        raise _refuse(exc) from exc


@router.delete("/documents/{document_id}", response_model=DocumentList)
def delete_document(document_id: str) -> DocumentList:
    """Forget a document: its passages and the stored file."""
    try:
        store.remove(document_id)
        return _listing()
    except AtlasError as exc:
        raise _refuse(exc) from exc
