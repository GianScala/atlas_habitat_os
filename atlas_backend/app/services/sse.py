"""Server-sent event framing.

One JSON object per event, on a single `data:` line. Keeping every event on
one line means the browser-side parser never has to reassemble a payload split
across lines, which is where hand-rolled SSE clients usually go wrong.
"""

from collections.abc import Iterable, Iterator
from typing import Any

from pydantic import BaseModel

# Proxies that buffer responses defeat streaming entirely. This header asks
# nginx not to, and the comment line below opens the stream immediately so the
# browser fires `onopen` without waiting for the first real event.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

MEDIA_TYPE = "text/event-stream"

PRELUDE = ": atlas stream open\n\n"


def encode(event: BaseModel) -> str:
    """One pydantic event as an SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


def stream(events: Iterable[Any]) -> Iterator[str]:
    """Wrap an event iterable as an SSE byte stream."""
    yield PRELUDE
    for event in events:
        yield encode(event)
