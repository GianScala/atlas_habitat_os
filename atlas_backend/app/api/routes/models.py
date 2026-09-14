"""Choosing, installing and removing the model that answers questions.

Everything here is about the local runtime, with one exception: switching
back to the Anthropic API is also a choice, and it belongs on the same page
as the choice it competes with.

Installing streams, because a model is several gigabytes and a request that
sits silent for ten minutes is indistinguishable from one that has died.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_app_settings
from app.config import Settings
from app.core.errors import AtlasError, QueryError
from app.core.logging import get_logger
from app.llm import inventory, providers, selection, warm
from app.llm.catalogue import canonical
from app.schemas.models import (
    ActivateRequest,
    ModelRequest,
    ModelsStatus,
    PullDoneEvent,
    PullErrorEvent,
    PullProgressEvent,
    PullStartEvent,
)
from app.services import sse

log = get_logger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsStatus)
def list_models(settings: Settings = Depends(get_app_settings)) -> ModelsStatus:
    """Everything the Models page draws: what is installed, and what answers."""
    return inventory.snapshot(settings)


@router.post("/active", response_model=ModelsStatus)
def activate(
    request: ActivateRequest, settings: Settings = Depends(get_app_settings)
) -> ModelsStatus:
    """Answer questions with this model from now on.

    A model that is not installed can still be selected — the page then says
    so plainly, which is more useful than refusing the click. What cannot
    happen is a stale provider surviving the change, so the cache is dropped.

    Switching is the other moment Ollama's KV cache is guaranteed cold: the new
    model comes off disk knowing nothing, and whoever asks the next question
    pays to prefill the whole system prompt. So the warm-up is kicked off here,
    in the background — the click returns at once either way.

    Only on a real change, though. Re-selecting the model already in force is a
    common click, and its cache is exactly as warm as it was a moment ago;
    warming it again would put a minute of pointless work on the one runner
    everybody shares, for nothing.
    """
    before = selection.active(settings)
    after = selection.choose(request.provider, request.model, settings)
    providers.forget()

    if after != before:
        warm.warm(settings)

    return inventory.snapshot(settings)


@router.post(
    "/install",
    response_class=StreamingResponse,
    responses={200: {"content": {sse.MEDIA_TYPE: {}}}},
)
def install(
    request: ModelRequest, settings: Settings = Depends(get_app_settings)
) -> StreamingResponse:
    """Download a model, streaming Ollama's own progress as it goes."""
    name = canonical(request.name)
    if not name:
        raise QueryError("Name the model to install, as Ollama lists it.")

    log.info("Installing model %s", name)

    return StreamingResponse(
        sse.stream(_pull(name, settings)),
        media_type=sse.MEDIA_TYPE,
        headers=sse.SSE_HEADERS,
    )


def _pull(name: str, settings: Settings):
    """The install, as a stream of events.

    Ollama reports progress per layer, so `completed`/`total` restart several
    times over one download. They are passed through as they come rather than
    being smoothed into a single bar: a page that says "layer 3 of 7, 60%" is
    honest, and one that invents a monotonic percentage is not.
    """
    yield PullStartEvent(name=name)

    try:
        for update in inventory.client(settings).pull(name):
            status = str(update.get("status", ""))
            completed = update.get("completed")
            total = update.get("total")
            percent = (
                round(completed / total * 100, 1)
                if isinstance(completed, (int, float))
                and isinstance(total, (int, float))
                and total > 0
                else None
            )
            yield PullProgressEvent(
                status=status,
                completed=int(completed) if isinstance(completed, (int, float)) else None,
                total=int(total) if isinstance(total, (int, float)) else None,
                percent=percent,
            )
    except AtlasError as exc:
        log.warning("Install of %s failed: %s", name, exc.message)
        yield PullErrorEvent(
            message=exc.message, kind=getattr(exc, "kind", "ollama")
        )
        return

    log.info("Installed model %s", name)
    yield PullDoneEvent(name=name, message=f"{name} is installed and ready to use.")


@router.post("/remove", response_model=ModelsStatus)
def remove(
    request: ModelRequest, settings: Settings = Depends(get_app_settings)
) -> ModelsStatus:
    """Delete a model from disk, freeing its several gigabytes.

    A POST rather than a DELETE with a path parameter: model names carry
    colons and slashes, and encoding them into a path to take them straight
    back out again is a bug waiting to happen.
    """
    name = canonical(request.name)
    inventory.client(settings).delete(name)

    # If that was the model in force, the cached provider now points at
    # weights that are gone. The page reports it as uninstalled either way.
    providers.forget()

    log.info("Removed model %s", name)
    return inventory.snapshot(settings)
