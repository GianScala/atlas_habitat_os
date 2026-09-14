"""Stored chat threads: list, read, delete.

Asking a question is `POST /api/chat` — these endpoints are about the history
around it.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_app_settings, get_conversations
from app.config import Settings
from app.core.errors import AtlasError
from app.schemas.conversations import (
    ConversationDetail,
    ConversationSummary,
    DeleteResult,
)
from app.services.transcript import to_transcript
from app.storage.conversation_repository import ConversationRepository

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    repository: ConversationRepository = Depends(get_conversations),
    settings: Settings = Depends(get_app_settings),
) -> list[ConversationSummary]:
    """Every stored thread, most recently active first."""
    rows = repository.list(limit=settings.max_conversations_listed)
    return [
        ConversationSummary(
            conversation_id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=row["message_count"],
        )
        for row in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str,
    repository: ConversationRepository = Depends(get_conversations),
) -> ConversationDetail:
    """One thread, projected back into a readable transcript."""
    try:
        conversation = repository.get(conversation_id)
    except AtlasError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return ConversationDetail(
        conversation_id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(conversation.messages),
        messages=to_transcript(conversation.messages),
    )


@router.delete("/{conversation_id}", response_model=DeleteResult)
def delete_conversation(
    conversation_id: str,
    repository: ConversationRepository = Depends(get_conversations),
) -> DeleteResult:
    """Forget one thread."""
    return DeleteResult(deleted=1 if repository.delete(conversation_id) else 0)


@router.delete("", response_model=DeleteResult)
def delete_all_conversations(
    repository: ConversationRepository = Depends(get_conversations),
) -> DeleteResult:
    """Forget every thread. The interface confirms before calling this."""
    return DeleteResult(deleted=repository.delete_all())
