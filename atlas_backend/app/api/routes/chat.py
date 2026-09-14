"""The chat endpoint.

Answers stream over SSE. The handler is a plain `def`, so Starlette runs the
blocking agent loop in its threadpool and the event loop stays free.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import get_agent, get_conversations
from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.schemas.chat import ChatRequest
from app.services import sse
from app.services.agent import Agent
from app.storage.conversation_repository import ConversationRepository

log = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_class=StreamingResponse,
    responses={200: {"content": {sse.MEDIA_TYPE: {}}}},
)
def chat(
    request: ChatRequest,
    agent: Agent = Depends(get_agent),
    repository: ConversationRepository = Depends(get_conversations),
) -> StreamingResponse:
    """Ask a question. Returns a stream of events, not a single answer.

    Omit `conversation_id` to start a thread; the `start` event carries the id
    to use for follow-ups. Pass an existing id to continue where you left off —
    the stored history goes back to the model with the new question.
    """
    question = request.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Enter a non-empty question.")

    try:
        if request.conversation_id:
            conversation = repository.get(request.conversation_id)
        else:
            conversation = repository.create()
    except AtlasError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # A thread is named after the question that opened it.
    repository.title_if_untitled(conversation, question)

    log.info("Question received on conversation %s", conversation.id)

    return StreamingResponse(
        sse.stream(agent.run(conversation, question)),
        media_type=sse.MEDIA_TYPE,
        headers=sse.SSE_HEADERS,
    )
