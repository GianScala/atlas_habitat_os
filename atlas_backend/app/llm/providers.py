"""Building the provider that is currently in force.

Providers are cached per (provider, model) because both hold a connection
pool worth reusing, and because building the Anthropic one validates the key.
The cache is cleared whenever the choice changes or a model is deleted, so a
provider pointing at weights that are no longer on disk cannot be handed out.
"""

from functools import lru_cache

from app.config import Settings, get_settings
from app.llm.base import Provider
from app.llm.selection import ANTHROPIC, Choice, active


@lru_cache(maxsize=8)
def _build(provider: str, model: str) -> Provider:
    # Imported here rather than at module scope so that a backend with no
    # anthropic package installed can still serve local models.
    if provider == ANTHROPIC:
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model)

    from app.llm.ollama_provider import OllamaProvider

    return OllamaProvider(model=model)


def build(choice: Choice) -> Provider:
    """The provider for one choice. Raises if it cannot be used as configured."""
    return _build(choice.provider, choice.model)


def active_provider(settings: Settings | None = None) -> Provider:
    """The provider answering questions right now."""
    return build(active(settings or get_settings()))


def forget() -> None:
    """Drop the cached providers. Called when the choice or the models change."""
    _build.cache_clear()
