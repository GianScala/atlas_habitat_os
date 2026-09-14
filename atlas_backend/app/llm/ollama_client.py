"""Talking to the Ollama daemon over HTTP.

Ollama runs as a small server on this machine — by default on port 11434 —
and everything we need from it is four calls: what is installed, download
this, delete that, and answer a question. This module is only transport: it
speaks JSON and newline-delimited JSON streams, and turns every way the call
can fail into a ModelError that says what to do about it.

Nothing here knows what a conversation is. The translation between our
history and Ollama's message format lives in `translate.py`, and the agent
side of it in `ollama_provider.py`.
"""

import json
from collections.abc import Iterator
from typing import Any

import requests

from app.core.errors import ModelError
from app.core.logging import get_logger

log = get_logger(__name__)

# Enough for the daemon to answer "are you there"; a model that has to be
# read off disk first is given the much longer read timeout instead.
CONNECT_TIMEOUT = 5
LIST_TIMEOUT = 10

# A pull of several gigabytes goes quiet between progress lines on a slow
# link, and that is not a reason to give up on it.
PULL_READ_TIMEOUT = 900


class OllamaUnavailable(ModelError):
    """The daemon is not answering. Almost always: it is not running."""

    def __init__(self, host: str, detail: str = "") -> None:
        super().__init__(
            f"Could not reach Ollama at {host}. Start it with `ollama serve` "
            "(or open the Ollama app), then try again."
            + (f" [{detail}]" if detail else ""),
            kind="ollama_offline",
            recoverable=False,
        )


class OllamaClient:
    """One Ollama daemon."""

    def __init__(self, host: str, timeout: int = 600) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    # -- plumbing ----------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.host}{path}"

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        stream: bool = False,
        read_timeout: int | None = None,
    ) -> requests.Response:
        try:
            response = self.session.request(
                method,
                self._url(path),
                json=payload,
                stream=stream,
                timeout=(CONNECT_TIMEOUT, read_timeout or self.timeout),
            )
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailable(self.host) from exc
        except requests.exceptions.Timeout as exc:
            raise ModelError(
                f"Ollama did not answer within {read_timeout or self.timeout}s.",
                kind="ollama_timeout",
            ) from exc
        except requests.RequestException as exc:
            raise ModelError(f"Ollama request failed: {exc}", kind="ollama") from exc

        if response.status_code >= 400:
            raise ModelError(_reason(response), kind=_kind(response.status_code))

        return response

    def _json(self, method: str, path: str, payload: dict | None = None,
              read_timeout: int | None = None) -> dict:
        response = self._request(method, path, payload, read_timeout=read_timeout)
        try:
            body = response.json()
        except ValueError as exc:
            raise ModelError(
                f"Ollama returned something that was not JSON on {path}.",
                kind="ollama",
            ) from exc
        return body if isinstance(body, dict) else {}

    def _stream(
        self, path: str, payload: dict, read_timeout: int | None = None
    ) -> Iterator[dict]:
        """Newline-delimited JSON, one object per line, as they arrive."""
        response = self._request(
            "POST", path, payload, stream=True, read_timeout=read_timeout
        )

        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    log.warning("Skipping unparseable line from %s: %.120s", path, line)
                    continue
                if isinstance(parsed, dict):
                    # A stream can carry a failure partway through; it arrives
                    # as a line rather than a status code.
                    if parsed.get("error"):
                        raise ModelError(str(parsed["error"]), kind="ollama")
                    yield parsed
        except requests.exceptions.ChunkedEncodingError as exc:
            raise ModelError(
                "Ollama closed the connection midway through the answer.",
                kind="ollama",
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailable(self.host) from exc
        finally:
            response.close()

    # -- the daemon --------------------------------------------------------

    def version(self) -> str:
        """The running Ollama version. Doubles as the reachability check."""
        payload = self._json("GET", "/api/version", read_timeout=LIST_TIMEOUT)
        return str(payload.get("version", ""))

    def installed(self) -> list[dict[str, Any]]:
        """Every model already on disk, newest first."""
        body = self._json("GET", "/api/tags", read_timeout=LIST_TIMEOUT)
        models = body.get("models")
        return [m for m in models if isinstance(m, dict)] if isinstance(models, list) else []

    def loaded(self) -> list[dict[str, Any]]:
        """Every model currently held in memory, with what it is holding.

        Distinct from `installed`, and the distinction is the whole point on a
        machine with 16 GB: what is on disk costs nothing, what is loaded is
        competing with everything else running. Two resident models on a small
        Mac means each question evicts the other and pays to read it back.
        """
        body = self._json("GET", "/api/ps", read_timeout=LIST_TIMEOUT)
        models = body.get("models")
        return [m for m in models if isinstance(m, dict)] if isinstance(models, list) else []

    def show(self, name: str) -> dict[str, Any]:
        """One model's card, including what it can do.

        Recent Ollama reports a `capabilities` list — "tools", "thinking",
        "vision". That is measured rather than assumed, so it beats anything
        we could hardcode about a model.
        """
        return self._json("POST", "/api/show", {"model": name}, read_timeout=LIST_TIMEOUT)

    def pull(self, name: str) -> Iterator[dict[str, Any]]:
        """Download a model, yielding progress as it goes."""
        yield from self._stream(
            "/api/pull", {"model": name, "stream": True}, read_timeout=PULL_READ_TIMEOUT
        )

    def delete(self, name: str) -> None:
        """Remove a model from disk."""
        self._request("DELETE", "/api/delete", {"model": name}, read_timeout=LIST_TIMEOUT)

    def chat(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Stream one chat completion."""
        return self._stream("/api/chat", payload, read_timeout=self.timeout)

    def chat_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One chat completion, waited for rather than streamed.

        Only the prefix warm-up uses this. Nothing a person is watching should
        go through it — a streamed answer starts appearing in a second and this
        returns when the whole thing is finished.

        WHY THERE IS NO CANCEL. An earlier version took a stop Event and closed
        the socket to abandon a warm-up when a question arrived. It did not
        work: with `stream=True` requests still blocks until the first byte,
        and Ollama sends nothing until the prefill is done, so the thread meant
        to interrupt a sixty-second prefill only started after it. Measured, it
        cancelled at 68.9s.

        Nor was it worth repairing, which is the more useful half. A question
        that WAITS for a warm-up inherits its cache and then costs seconds; one
        that cancels it must prefill from near scratch and pays the whole cost
        itself. The two come out within a few seconds of each other, and
        waiting wins outright whenever the warm-up is more than a little way
        in. The real protection is not starting warm-ups that are not worth
        their runner — which is `warm.priority()`, and which does work.
        """
        return self._json("POST", "/api/chat", payload, read_timeout=self.timeout)


def _reason(response: requests.Response) -> str:
    """The clearest sentence we can get out of a failed Ollama response."""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    except ValueError:
        pass
    return f"Ollama returned HTTP {response.status_code}."


def _kind(status_code: int) -> str:
    """404 from Ollama means the model is not installed, which is fixable."""
    return "model_not_installed" if status_code == 404 else "ollama"
