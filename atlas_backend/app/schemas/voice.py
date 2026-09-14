"""Wire shapes for the optional, fully local voice interface."""

from pydantic import BaseModel, Field


class VoiceStatus(BaseModel):
    transcription_ready: bool
    synthesis_ready: bool
    transcription_detail: str
    synthesis_detail: str
    max_recording_mb: int
    voices: list["VoiceOption"] = Field(default_factory=list)
    active_voice: str = ""
    language: str = "auto"


class VoiceOption(BaseModel):
    id: str
    label: str


class VoiceChoice(BaseModel):
    voice: str = Field(max_length=160)
    language: str = Field(default="auto", pattern="^(auto|en|it|de|fr|es|pt)$")


class VoiceTranscription(BaseModel):
    text: str
    processing_ms: int = 0


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12_000)
    voice: str | None = Field(default=None, max_length=160)
