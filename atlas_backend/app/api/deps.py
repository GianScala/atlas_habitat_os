"""Shared dependencies for the route handlers."""

from app.config import Settings, get_settings
from app.llm import providers
from app.llm.base import Provider
from app.services.agent import Agent
from app.storage.conversation_repository import ConversationRepository, get_repository


def get_provider() -> Provider:
    """The model in force right now.

    Resolved per request rather than once at startup: the choice lives in the
    database and can change between two questions in the same conversation.
    The providers themselves are cached, so this is a dictionary lookup unless
    the choice actually changed.
    """
    return providers.active_provider()


def get_agent() -> Agent:
    """An agent bound to the active model and settings."""
    return Agent(get_provider(), get_settings())


def get_conversations() -> ConversationRepository:
    """Durable chat history."""
    return get_repository()


def get_app_settings() -> Settings:
    return get_settings()
