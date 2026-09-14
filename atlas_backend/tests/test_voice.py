"""The optional voice path stays local and fails clearly when unconfigured."""

import wave
from array import array
from pathlib import Path

import pytest

from app.config import Settings
from app.services import voice, voice_preferences, voice_synthesis


def write_wave(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(array("h", samples).tobytes())


def test_unconfigured_voice_is_reported_unavailable() -> None:
    state = voice.readiness(
        Settings(voice_whisper_cli="missing-whisper", voice_piper_cli="missing-piper")
    )
    assert state.transcription_ready is False
    assert state.synthesis_ready is False
    assert "VOICE_WHISPER_MODEL" in state.transcription_detail
    assert "VOICE_PIPER_MODEL" in state.synthesis_detail


def test_transcription_converts_audio_and_reads_whisper_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    whisper_model = tmp_path / "whisper.bin"
    whisper_model.write_bytes(b"model")
    settings = Settings(voice_whisper_model=str(whisper_model))
    ready = voice.VoiceReadiness(True, False, "ready", "missing")
    monkeypatch.setattr(voice, "readiness", lambda _settings: ready)
    monkeypatch.setattr(voice, "_executable", lambda value: value)

    commands: list[list[str]] = []

    def fake_run(command: list[str], _timeout: int):
        commands.append(command)
        if command[0] == "ffmpeg":
            write_wave(Path(command[-1]), [500] * 16000)
        if "-of" in command:
            output = Path(command[command.index("-of") + 1]).with_suffix(".txt")
            output.write_text("  how much   water today? \n", encoding="utf-8")

    monkeypatch.setattr(voice, "_run", fake_run)
    assert voice.transcribe(b"browser audio", settings) == "how much water today?"
    assert commands[0][0] == "ffmpeg"
    assert commands[1][0] == "whisper-cli"
    assert "-l" in commands[1]
    assert "-nf" in commands[1]  # Low-confidence recordings must not trigger repeated decoding.
    assert commands[1][commands[1].index("-bs") + 1] == "1"


def test_synthesis_returns_the_wave_written_by_piper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    piper_model = tmp_path / "voice.onnx"
    piper_model.write_bytes(b"model")
    settings = Settings(voice_piper_model=str(piper_model))
    ready = voice.VoiceReadiness(False, True, "missing", "ready")
    monkeypatch.setattr(voice, "readiness", lambda _settings: ready)
    monkeypatch.setattr(voice, "_executable", lambda value: value)
    monkeypatch.setattr(
        voice_preferences, "installed", lambda _settings: {"voice": piper_model}
    )

    def unavailable(*args):
        raise ImportError("Piper is installed separately")

    monkeypatch.setattr(voice_synthesis, "render", unavailable)

    def fake_run(command: list[str], _timeout: int):
        output = Path(command[command.index("-f") + 1])
        output.write_bytes(b"RIFF-local-wave")

    monkeypatch.setattr(voice, "_run", fake_run)
    assert voice.synthesize("Water is within target.", settings) == b"RIFF-local-wave"


def test_silent_recording_is_refused_before_decoding(tmp_path):
    path = tmp_path / "silent.wav"
    write_wave(path, [0] * 16000)
    with pytest.raises(voice.VoiceError, match="No speech"):
        voice._trim_silence(path)


def test_quiet_edges_trimmed_without_losing_speech(tmp_path):
    path = tmp_path / "padded.wav"
    speech = [500] * 16000
    write_wave(path, [0] * 32000 + speech + [0] * 32000)
    voice._trim_silence(path)
    with wave.open(str(path), "rb") as result:
        samples = array("h", result.readframes(result.getnframes()))
    assert len(samples) == 22400  # One second speech plus 200 ms on each edge.
    assert list(samples[3200:19200]) == speech


def test_recording_duration_is_bounded(tmp_path):
    path = tmp_path / "long.wav"
    write_wave(path, [500] * (16000 * 61))
    with pytest.raises(voice.VoiceError, match="under one minute"):
        voice._trim_silence(path)


def test_voice_selection_persists_and_rejects_paths(temp_database, tmp_path, monkeypatch):
    from app.core.errors import QueryError

    monkeypatch.setattr(voice_preferences, "installed", lambda _settings: {
        "first": tmp_path / "first.onnx", "second": tmp_path / "second.onnx",
    })
    settings = Settings()
    voice_preferences.choose("second", "it", settings)
    assert voice_preferences.selected(settings) == "second"
    assert voice_preferences.language(settings) == "it"
    with pytest.raises(QueryError, match="installed"):
        voice_preferences.choose("../../private", "en", settings)
    assert voice_preferences.selected(settings) == "second"


def test_voice_http_endpoints(temp_database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes.voice import router

    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(
        voice, "synthesize", lambda text, settings, voice_id: b"RIFF-local-wave"
    )
    monkeypatch.setattr(voice, "transcribe", lambda recording, settings: "Water today?")
    with TestClient(app) as client:
        response = client.post("/voice/synthesize", json={"text": "Water today?"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.headers["cache-control"] == "no-store"
        assert client.post("/voice/synthesize", json={"text": " "}).status_code == 400
        response = client.post("/voice/transcribe", files={"file": ("recording", b"audio")})
        assert response.json()["text"] == "Water today?"
        assert response.json()["processing_ms"] >= 0
        response = client.post("/voice/transcribe", files={"file": ("empty", b"")})
        assert response.status_code == 400


def test_browser_audio_conversion_rejects_playlists(tmp_path, monkeypatch):
    """Exercise the real decoder when installed, without contacting a service."""
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("Optional ffmpeg executable is not installed")
    monkeypatch.setattr(
        voice, "readiness", lambda _settings: voice.VoiceReadiness(True, False, "", "")
    )
    # A playlist must not make the converter read another local file.
    recording = tmp_path / "other.wav"
    write_wave(recording, [500] * 16000)
    playlist = f"ffconcat version 1.0\nfile '{recording}'\n".encode()
    with pytest.raises(voice.VoiceError, match="whitelist"):
        voice.transcribe(playlist, Settings())
