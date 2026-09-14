"""What is installed, what it can do, and whether we can answer at all.

Everything the Models page draws is assembled here, from three sources that
disagree in useful ways:

  THE CATALOGUE says what we offer and what we expect of it.
  THE DAEMON says what is actually on disk, and — for anything installed —
    what those weights can really do.
  THE SELECTION says which one is answering questions.

Where the daemon and the catalogue disagree about a model's capabilities, the
daemon wins and the page says the figure was measured. Guessing wrong about
tool support is the one mistake here with teeth: a model that cannot call a
tool cannot read a sensor, and will invent the reading instead.
"""

from typing import Any

from app.config import Settings, get_settings
from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.llm import catalogue, selection
from app.llm.catalogue import CatalogueEntry, canonical
from app.llm.ollama_client import OllamaClient
from app.schemas.models import (
    LoadedModel,
    ModelInfo,
    ModelsStatus,
    ProviderInfo,
    RuntimeStatus,
)

log = get_logger(__name__)

# Capabilities are a property of the weights, so they are cached against the
# digest: the same model re-pulled under a new tag is not re-interrogated,
# and a model rebuilt under the same tag is.
_capabilities: dict[str, list[str]] = {}


def client(settings: Settings | None = None) -> OllamaClient:
    settings = settings or get_settings()
    return OllamaClient(settings.ollama_base, settings.ollama_timeout)


def quick_check(settings: Settings | None = None) -> tuple[bool, str | None]:
    """Could a question be answered right now? One call, for the health badge.

    Deliberately cheaper than `snapshot`: it asks the daemon what is on disk
    and nothing else. Whether the chosen model can call tools is a question
    for the Models page, which has room to explain the answer.
    """
    settings = settings or get_settings()
    choice = selection.active(settings)

    if not choice.local:
        if settings.anthropic_api_key:
            return True, None
        return False, "ANTHROPIC_API_KEY is not set."

    try:
        rows = client(settings).installed()
    except AtlasError as exc:
        return False, exc.message

    installed = {canonical(str(row.get("model") or row.get("name") or "")) for row in rows}
    if choice.model not in installed:
        return False, f"{choice.model} is not installed. Install it on the Models page."

    return True, None


def snapshot(settings: Settings | None = None) -> ModelsStatus:
    """The whole state of the Models page in one read."""
    settings = settings or get_settings()
    choice = selection.active(settings)

    runtime, installed = _runtime(settings)
    models = _models(installed, choice)
    ready, warning = _readiness(choice, runtime, models, settings)

    return ModelsStatus(
        provider=choice.provider,
        model=choice.model,
        label=_label(choice),
        local=choice.local,
        ready=ready,
        warning=warning,
        providers=_providers(choice, runtime, settings),
        runtime=runtime,
        models=models,
    )


def _label(choice: selection.Choice) -> str:
    return f"{choice.model} (local)" if choice.local else f"{choice.model} (Anthropic)"


# -- the daemon -------------------------------------------------------------


def _runtime(settings: Settings) -> tuple[RuntimeStatus, dict[str, dict[str, Any]]]:
    """The daemon's state, and everything it has on disk keyed by name.

    A daemon that is not running is a normal state for this page — it is the
    page you go to in order to fix that — so it is reported, not raised.
    """
    status = RuntimeStatus(
        reachable=False,
        host=settings.ollama_base,
        models_dir=settings.resolved_ollama_models_dir,
    )

    daemon = client(settings)

    try:
        status.version = daemon.version() or None
        rows = daemon.installed()
    except AtlasError as exc:
        status.detail = exc.message
        return status, {}

    status.reachable = True
    installed = {canonical(str(row.get("model") or row.get("name") or "")): row
                 for row in rows}
    installed.pop("", None)
    status.installed_count = len(installed)
    status.loaded = _loaded(daemon)

    for name, row in installed.items():
        row["capabilities"] = _capabilities_of(daemon, name, str(row.get("digest", "")))

    return status, installed


def _loaded(daemon: OllamaClient) -> list[LoadedModel]:
    """What is in memory right now. Never fatal — it is a diagnostic."""
    try:
        rows = daemon.loaded()
    except AtlasError as exc:
        log.info("Could not read loaded models: %s", exc.message)
        return []

    resident = []
    for row in rows:
        size = row.get("size_vram") or row.get("size") or 0
        resident.append(
            LoadedModel(
                name=canonical(str(row.get("model") or row.get("name") or "")),
                bytes_resident=int(size) if isinstance(size, (int, float)) else 0,
                context_length=row.get("context_length"),
                expires_at=str(row["expires_at"]) if row.get("expires_at") else None,
            )
        )
    return resident


def _capabilities_of(daemon: OllamaClient, name: str, digest: str) -> list[str]:
    """What these weights can do, as the daemon reports it.

    Older Ollama builds do not report capabilities at all. An empty list means
    "not measured", and the catalogue's expectation stands.
    """
    if digest and digest in _capabilities:
        return _capabilities[digest]

    try:
        card = daemon.show(name)
    except AtlasError as exc:
        log.info("Could not read capabilities for %s: %s", name, exc.message)
        return []

    found = card.get("capabilities")
    measured = [str(c) for c in found] if isinstance(found, list) else []

    if digest:
        _capabilities[digest] = measured
    return measured


# -- the list ---------------------------------------------------------------


def _models(
    installed: dict[str, dict[str, Any]], choice: selection.Choice
) -> list[ModelInfo]:
    """The catalogue first, in its own order, then anything else on disk."""
    listed = [
        _entry(entry, installed.get(entry.name), choice)
        for entry in catalogue.CATALOGUE
    ]

    extra = [
        _unlisted(name, row, choice)
        for name, row in installed.items()
        if catalogue.find(name) is None
    ]

    return listed + sorted(extra, key=lambda model: model.name)


def _entry(
    entry: CatalogueEntry, row: dict[str, Any] | None, choice: selection.Choice
) -> ModelInfo:
    model = ModelInfo(
        name=entry.name,
        description=entry.description,
        size_note=entry.size_note,
        badge=entry.badge or None,
        supports_tools=entry.tools,
        supports_thinking=entry.thinks,
        active=choice.local and choice.model == entry.name,
    )
    return _measure(model, row)


def _unlisted(
    name: str, row: dict[str, Any], choice: selection.Choice
) -> ModelInfo:
    """A model the crew installed themselves.

    We have no description for it and will not invent one. Its capabilities
    come from the daemon like everything else — and until they do, tool
    support is not assumed, because assuming it is the dangerous direction.
    """
    model = ModelInfo(
        name=name,
        description="Installed from the Ollama catalogue.",
        size_note="",
        in_catalogue=False,
        supports_tools=False,
        active=choice.local and choice.model == name,
    )
    return _measure(model, row)


def _measure(model: ModelInfo, row: dict[str, Any] | None) -> ModelInfo:
    """Fold in what the daemon knows about a model that is on disk."""
    if row is None:
        return model

    model.installed = True
    size = row.get("size")
    model.size_bytes = int(size) if isinstance(size, (int, float)) else None

    details = row.get("details") or {}
    if isinstance(details, dict):
        model.parameter_size = details.get("parameter_size")
        model.quantisation = details.get("quantization_level")

    capabilities = row.get("capabilities") or []
    if capabilities:
        model.capabilities_measured = True
        model.supports_tools = "tools" in capabilities
        model.supports_thinking = "thinking" in capabilities

    return model


# -- can we answer? ---------------------------------------------------------


def _providers(
    choice: selection.Choice, runtime: RuntimeStatus, settings: Settings
) -> list[ProviderInfo]:
    return [
        ProviderInfo(
            key=selection.OLLAMA,
            label="Ollama",
            description=(
                "Questions, telemetry and retrieved passages go to the configured "
                "Ollama host. Keep that host local and trusted for private inference."
            ),
            available=runtime.reachable,
            detail=runtime.detail
            or (f"Ollama {runtime.version}" if runtime.version else None),
            model=selection.model_for(selection.OLLAMA, settings),
            active=choice.provider == selection.OLLAMA,
            local=True,
        ),
        ProviderInfo(
            key=selection.ANTHROPIC,
            label="Anthropic API",
            description=(
                "Claude, in the cloud. Questions, retrieved telemetry, document "
                "passages and conversation context are sent to Anthropic."
            ),
            available=bool(settings.anthropic_api_key),
            detail=None
            if settings.anthropic_api_key
            else "ANTHROPIC_API_KEY is not set in the backend's .env file.",
            model=selection.model_for(selection.ANTHROPIC, settings),
            active=choice.provider == selection.ANTHROPIC,
            local=False,
        ),
    ]


def _readiness(
    choice: selection.Choice,
    runtime: RuntimeStatus,
    models: list[ModelInfo],
    settings: Settings,
) -> tuple[bool, str | None]:
    """Whether a question asked right now would be answered, and if not, why."""
    if not choice.local:
        if settings.anthropic_api_key:
            return True, None
        return False, (
            "The Anthropic API is selected but ANTHROPIC_API_KEY is not set. "
            "Add it to the backend's .env file, or switch to a local model."
        )

    if not runtime.reachable:
        return False, (
            f"Ollama is not answering at {runtime.host}. Start it — `ollama "
            "serve`, or open the Ollama app — and this page will fill in."
        )

    active_model = next((m for m in models if m.active), None)

    if active_model is None or not active_model.installed:
        return False, (
            f"{choice.model} is selected but not installed yet. Install it "
            "below, or choose one that is already on disk."
        )

    if not active_model.supports_tools:
        measured = (
            "Ollama reports it cannot call tools"
            if active_model.capabilities_measured
            else "It is not expected to support tool calling"
        )
        return True, (
            f"{choice.model} cannot query the habitat. {measured}, and every "
            "answer ATLAS gives is built from a query. Pick a model marked "
            "as calling tools."
        )

    # Said only when nothing worse is wrong, because it is a slowness rather
    # than a failure — but on a machine this size it is the slowness that
    # makes an answer take a minute instead of ten seconds. Two resident
    # models do not share memory politely: each question evicts the other and
    # pays to read several gigabytes back off disk first.
    if len(runtime.loaded) > 1:
        names = ", ".join(m.name for m in runtime.loaded)
        held = sum(m.bytes_resident for m in runtime.loaded) / 1e9
        return True, (
            f"{len(runtime.loaded)} models are loaded at once ({names}), "
            f"holding {held:.1f} GB between them. They will keep evicting each "
            "other, and every question pays to load one back. Use one model "
            "until it drops out of memory on its own."
        )

    return True, None
