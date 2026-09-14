"""Shapes for the Connectors page: the documents the assistant may read."""

from pydantic import BaseModel


class DocumentEntry(BaseModel):
    """One uploaded document, as the page lists it."""

    id: str
    filename: str
    #: PDF, Word document, CSV, text file, Markdown.
    kind: str
    bytes: int
    characters: int
    #: How many retrievable passages it was cut into.
    chunks: int
    #: vector (embedded) or lexical (matched on shared words).
    indexing: str
    #: Whether the assistant may search it right now.
    connected: bool
    note: str
    uploaded_at: float


class ConnectorStatus(BaseModel):
    """What the knowledge base can do on this machine."""

    #: An embedding model is installed and reachable.
    embeddings_ready: bool
    #: Why not, when it is not. Empty when it is.
    embeddings_detail: str
    embedding_model: str
    #: The file types accepted, said once.
    accepts: str
    max_mb: int
    #: How many documents the assistant may currently search.
    connected: int


class DocumentList(BaseModel):
    documents: list[DocumentEntry]
    status: ConnectorStatus


class ToggleUpdate(BaseModel):
    connected: bool
