"""HTTP routes, one module per concern."""

from fastapi import APIRouter

from app.api.routes import (
    chat,
    connectors,
    conversations,
    dashboard,
    health,
    logbook,
    metadata,
    mission,
    models,
    naming,
    settings,
    voice,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(conversations.router)
api_router.include_router(dashboard.router)
api_router.include_router(mission.router)
api_router.include_router(logbook.router)
api_router.include_router(models.router)
api_router.include_router(settings.router)
api_router.include_router(metadata.router)
api_router.include_router(naming.router)
api_router.include_router(connectors.router)
api_router.include_router(voice.router)

__all__ = ["api_router"]
