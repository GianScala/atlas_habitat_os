"""Paying for the prompt prefix before anybody is waiting on it.

Every turn sends the same fixed prefix — the system prompt and the fourteen
tool schemas, some thousands of tokens — ahead of the question. Ollama keeps a
KV cache, so a turn whose prefix is already cached pays almost nothing for it.
A turn whose prefix is not pays for all of it, and on a laptop that prefills at
a few hundred tokens a second that is most of a minute of apparent silence.

The cache misses in two situations worth pre-empting: the daemon has just
loaded the model, and the crew has just switched to a different one. Neither is
a moment when anybody has asked anything yet, so the prefix is sent then.

THE RULE THIS MODULE EXISTS TO ENFORCE. Ollama serves one request at a time per
model. A warm-up is therefore not free background work — for as long as it
runs, it is standing in front of any question that arrives, and one started at
the wrong moment turns an eight-second answer into a seventy-second one. That
is not a hypothetical: it is what the first version of this file did, on the
most ordinary click there is (re-selecting the model already in use).

So the discipline is entirely about NOT STARTING. A warm-up that has begun runs
to the end — it cannot be interrupted in any way that helps, and
`OllamaClient.chat_once` records both why the attempt failed and why it turned
out not to be worth repairing. What is left, and what actually works, is
refusing to start one that is not worth a runner: not while a question is being
answered (`priority()`), not for a model already warm, and not twice over.

WHAT THIS IS NOT. It is not a speed-up. The prefill takes exactly as long as it
always did; this only moves it to a moment when nobody is watching. Sending
fewer tokens is the thing that makes it smaller, and that lives in
`tools/schemas.py`.

Failure here is never allowed to matter. A warm-up that cannot reach Ollama has
lost nothing the first question will not discover for itself, so it is logged
and dropped — never raised into a request, never into startup.
"""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from app.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_lock = threading.Lock()

# The (provider, model) being warmed, if any. Switching model twice in five
# seconds should not queue two warm-ups behind each other.
_in_flight: tuple[str, str] | None = None

# How many answers are in flight. A count rather than a flag: two questions can
# overlap, and the second finishing must not hand the runner back while the
# first is still using it.
_answering = 0


@contextmanager
def priority() -> Iterator[None]:
    """Claim the model for something a person is waiting on.

    Refuses to start new warm-ups until the last claim is released — including
    in the gaps between rounds of one answer, where a fresh one would otherwise
    slip in and stall round three. Cheap, reentrant across threads, and safe to
    wrap around work that raises.
    """
    global _answering
    with _lock:
        _answering += 1
    try:
        yield
    finally:
        with _lock:
            _answering -= 1
            _answering = max(_answering, 0)


def warm(settings: Settings | None = None) -> threading.Thread | None:
    """Warm the active model's prefix in the background, if that is worth doing.

    Returns the thread, so a test can wait for it, or None when there is
    nothing to do: a hosted model has no cache on this machine, a warm-up for
    this model is already running, or somebody is being answered right now and
    the runner is theirs.
    """
    settings = settings or get_settings()

    from app.llm import selection

    choice = selection.active(settings)
    if not choice.local:
        return None

    key = (choice.provider, choice.model)
    global _in_flight
    with _lock:
        if _answering:
            log.debug("Not warming %s: a question is being answered", choice.model)
            return None
        if _in_flight == key:
            return None
        _in_flight = key

    thread = threading.Thread(
        target=_guarded, args=(key,), name=f"prewarm-{choice.model}", daemon=True
    )
    thread.start()
    return thread


def _guarded(key: tuple[str, str]) -> None:
    """Run the warm-up and release the in-flight claim, whatever happens.

    The release belongs here rather than inside `_run`: this is the function
    that holds the claim, and a claim whose reset lives inside the work it
    guards is one unhandled exit away from being stranded forever — after
    which no model is ever warmed again, silently.
    """
    global _in_flight
    try:
        _run(key)
    finally:
        with _lock:
            if _in_flight == key:
                _in_flight = None


def _run(key: tuple[str, str]) -> None:
    """One warm-up, start to finish."""
    provider_key, model = key
    try:
        from app.llm import providers
        from app.llm.selection import Choice
        from app.services.prompt import system_prompt
        from app.tools import registry

        provider = providers.build(Choice(provider=provider_key, model=model))

        started = time.monotonic()
        provider.prewarm(system_prompt(provider), registry.schemas())
        log.info(
            "Warmed the prompt prefix for %s in %.1fs — the first question "
            "will not have to",
            model,
            time.monotonic() - started,
        )
    except Exception as exc:  # noqa: BLE001 - an optimisation, never a failure
        log.info("Could not warm the prompt prefix for %s: %s", model, exc)
