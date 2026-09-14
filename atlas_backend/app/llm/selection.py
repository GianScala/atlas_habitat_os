"""Which model answers questions, and where that choice lives.

A choice made on the Models page has to survive a restart, so it goes in the
database rather than in memory. The .env values are the fallback underneath:
no row means nobody has chosen yet.

The model is remembered PER PROVIDER, not once. Someone who tries the cloud
for one question and switches back should find their local model still
selected, not have to pick it again.
"""

import sqlite3
import time
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.core.errors import QueryError
from app.core.logging import get_logger
from app.llm import catalogue
from app.storage.database import connect

log = get_logger(__name__)

OLLAMA = "ollama"
ANTHROPIC = "anthropic"
PROVIDERS = (OLLAMA, ANTHROPIC)

PROVIDER_KEY = "llm_provider"
MODEL_KEY = "llm_model:"  # + provider


@dataclass(frozen=True)
class Choice:
    """The provider and model in force."""

    provider: str
    model: str

    @property
    def local(self) -> bool:
        return self.provider == OLLAMA


def _stored() -> dict[str, str]:
    """Every stored choice.

    A database that predates this table is not an error: it is a ATLAS that
    was installed before there was anything to choose, and the .env defaults
    are exactly right for it. The table appears on the next boot.
    """
    try:
        with connect() as connection:
            rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row["key"]: row["value"] for row in rows}


def _write(key: str, value: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
            """,
            (key, value, time.time()),
        )


def default_model(provider: str, settings: Settings | None = None) -> str:
    """The model a provider falls back to when nothing has been chosen."""
    settings = settings or get_settings()
    if provider == ANTHROPIC:
        return settings.anthropic_model
    return catalogue.canonical(settings.ollama_model)


def active(settings: Settings | None = None) -> Choice:
    """The choice in force: what was chosen, else what .env says."""
    settings = settings or get_settings()
    stored = _stored()

    provider = stored.get(PROVIDER_KEY) or settings.llm_provider
    if provider not in PROVIDERS:
        log.warning("Unknown provider %r stored; falling back to %s", provider, OLLAMA)
        provider = OLLAMA

    model = stored.get(MODEL_KEY + provider) or default_model(provider, settings)
    return Choice(provider=provider, model=model)


def model_for(provider: str, settings: Settings | None = None) -> str:
    """The model that would be used if this provider were selected."""
    return _stored().get(MODEL_KEY + provider) or default_model(provider, settings)


def choose(provider: str, model: str = "", settings: Settings | None = None) -> Choice:
    """Record the choice. Returns what is now in force."""
    settings = settings or get_settings()

    if provider not in PROVIDERS:
        raise QueryError(
            f"There is no provider called {provider!r}. "
            f"Choose one of: {', '.join(PROVIDERS)}."
        )

    name = catalogue.canonical(model) if provider == OLLAMA else model.strip()

    _write(PROVIDER_KEY, provider)
    if name:
        _write(MODEL_KEY + provider, name)

    chosen = Choice(provider=provider, model=name or model_for(provider, settings))
    log.info("Model set to %s on %s", chosen.model, chosen.provider)
    return chosen
