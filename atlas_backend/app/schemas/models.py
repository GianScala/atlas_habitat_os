"""Shapes for the Models page.

Mirrored in `atlas_frontend/src/lib/types.ts` — keep the two in step.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    """One model, offered or already installed."""

    name: str
    description: str
    #: Roughly what the download costs. From the catalogue, so it is present
    #: before the model exists on disk; `size_bytes` is the real figure after.
    size_note: str
    badge: str | None = None

    installed: bool = False
    size_bytes: int | None = None
    parameter_size: str | None = None
    quantisation: str | None = None

    supports_tools: bool = True
    supports_thinking: bool = False
    #: True once Ollama has told us what the weights on disk can do. Until
    #: then the two flags above are the catalogue's expectation.
    capabilities_measured: bool = False

    #: The model answering questions right now.
    active: bool = False
    #: False for anything installed that we do not offer ourselves.
    in_catalogue: bool = True


class ProviderInfo(BaseModel):
    """One way of answering a question."""

    key: str
    label: str
    description: str
    #: Usable right now — the daemon is up, or the key is set.
    available: bool
    detail: str | None = None
    #: The model this provider would use if selected.
    model: str
    active: bool
    local: bool


class LoadedModel(BaseModel):
    """A model held in memory right now."""

    name: str
    #: What it is holding. This is the number that competes with everything
    #: else running on the machine.
    bytes_resident: int = 0
    #: Context window it was loaded with — the KV cache is sized from this.
    context_length: int | None = None
    #: When it will be unloaded if nothing asks for it, ISO 8601.
    expires_at: str | None = None


class RuntimeStatus(BaseModel):
    """The local Ollama daemon."""

    reachable: bool
    host: str
    version: str | None = None
    detail: str | None = None
    #: Where the weights are kept, as best the backend can tell.
    models_dir: str
    installed_count: int = 0
    #: Resident right now. More than one on a small machine is the reason
    #: answers are slow: they evict each other and are read back per question.
    loaded: list[LoadedModel] = []


class ModelsStatus(BaseModel):
    """Everything the Models page draws."""

    provider: str
    model: str
    label: str
    local: bool
    #: Can a question actually be answered as things stand?
    ready: bool
    warning: str | None = None
    providers: list[ProviderInfo] = []
    runtime: RuntimeStatus
    models: list[ModelInfo] = []


class ActivateRequest(BaseModel):
    """Use this model from now on."""

    provider: Literal["ollama", "anthropic"]
    model: str = Field(default="", max_length=200)


class ModelRequest(BaseModel):
    """A model to install or remove, by its exact Ollama name."""

    name: str = Field(min_length=1, max_length=200)


# --- Install progress, as server-sent events -------------------------------


class PullStartEvent(BaseModel):
    type: Literal["start"] = "start"
    name: str


class PullProgressEvent(BaseModel):
    type: Literal["progress"] = "progress"
    #: Ollama's own words: "pulling manifest", "verifying sha256 digest"…
    status: str
    completed: int | None = None
    total: int | None = None
    #: 0…100, present only while bytes are actually moving.
    percent: float | None = None


class PullDoneEvent(BaseModel):
    type: Literal["done"] = "done"
    name: str
    message: str


class PullErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    kind: str = "ollama"
