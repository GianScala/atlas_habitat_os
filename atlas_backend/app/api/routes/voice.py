"""Browser voice capture backed only by local speech tools."""

import time

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.errors import AtlasError
from app.schemas.voice import (
    SpeechRequest,
    VoiceChoice,
    VoiceOption,
    VoiceStatus,
    VoiceTranscription,
)
from app.services import voice, voice_preferences

router = APIRouter(prefix="/voice", tags=["voice"])


def _refuse(exc: AtlasError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/status", response_model=VoiceStatus)
def status() -> VoiceStatus:
    settings = get_settings()
    state = voice.readiness(settings)
    return VoiceStatus(
        transcription_ready=state.transcription_ready,
        synthesis_ready=state.synthesis_ready,
        transcription_detail=state.transcription_detail,
        synthesis_detail=state.synthesis_detail,
        max_recording_mb=settings.voice_max_upload_mb,
        voices=[VoiceOption(id=key, label=voice_preferences.label(key))
                for key in voice_preferences.installed(settings)],
        active_voice=voice_preferences.selected(settings),
        language=voice_preferences.language(settings),
    )


@router.put("/settings", response_model=VoiceStatus)
def choose(body: VoiceChoice) -> VoiceStatus:
    voice_preferences.choose(body.voice, body.language, get_settings())
    return status()


@router.post("/transcribe", response_model=VoiceTranscription)
async def transcribe(file: UploadFile = File(...)) -> VoiceTranscription:
    settings = get_settings()
    limit = settings.voice_max_upload_mb * 1024 * 1024
    try:
        recording = await file.read(limit + 1)
        if len(recording) > limit:
            raise HTTPException(
                status_code=413,
                detail="Recording exceeds the local voice limit.",
            )
        if not recording:
            raise HTTPException(status_code=400, detail="The recording is empty.")
        started = time.perf_counter()
        text = await run_in_threadpool(voice.transcribe, recording, settings)
        return VoiceTranscription(
            text=text, processing_ms=int((time.perf_counter() - started) * 1000)
        )
    except AtlasError as exc:
        raise _refuse(exc) from exc
    finally:
        await file.close()


@router.post("/synthesize")
async def synthesize(body: SpeechRequest) -> Response:
    try:
        if not body.text.strip():
            raise HTTPException(status_code=400, detail="There is no text to read aloud.")
        audio = await run_in_threadpool(voice.synthesize, body.text, get_settings(), body.voice)
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
    except AtlasError as exc:
        raise _refuse(exc) from exc
