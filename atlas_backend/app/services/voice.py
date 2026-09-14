"""Offline speech recognition and synthesis through local open-source tools."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.core.errors import AtlasError
from app.core.logging import get_logger
from app.services import voice_preferences, voice_synthesis

log = get_logger(__name__)


class VoiceError(AtlasError):
    """A local voice tool is missing or failed."""

    status_code = 503


@dataclass(frozen=True)
class VoiceReadiness:
    transcription_ready: bool
    synthesis_ready: bool
    transcription_detail: str
    synthesis_detail: str


def _path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (Path(__file__).resolve().parents[2] / path).resolve()


def _executable(value: str) -> str | None:
    expanded = str(Path(value).expanduser())
    if "/" in expanded:
        path = Path(expanded)
        return str(path) if path.is_file() else None
    on_path = shutil.which(value)
    if on_path:
        return on_path
    # The documented launch command calls the venv's Python directly without
    # activating it, so console scripts in .venv/bin are not necessarily PATH.
    local = Path(__file__).resolve().parents[2] / ".venv" / "bin" / value
    return str(local) if local.is_file() else None


def readiness(settings: Settings) -> VoiceReadiness:
    ffmpeg = _executable(settings.voice_ffmpeg_cli)
    whisper = _executable(settings.voice_whisper_cli)
    whisper_model = (
        _path(settings.voice_whisper_model) if settings.voice_whisper_model else None
    )
    piper = _executable(settings.voice_piper_cli)

    transcription_ready = bool(ffmpeg and whisper and whisper_model and whisper_model.is_file())
    synthesis_ready = bool(piper and voice_preferences.installed(settings))

    transcription_detail = (
        "Ready — recordings stay on this machine."
        if transcription_ready
        else "Install ffmpeg and whisper.cpp, then set VOICE_WHISPER_MODEL."
    )
    synthesis_detail = (
        "Ready — answers are rendered on this machine."
        if synthesis_ready
        else "Install Piper, then set VOICE_PIPER_MODEL."
    )
    return VoiceReadiness(
        transcription_ready,
        synthesis_ready,
        transcription_detail,
        synthesis_detail,
    )


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VoiceError(f"The local voice tool could not run: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise VoiceError(detail[-500:] or "The local voice tool failed.")
    return result


def transcribe(recording: bytes, settings: Settings) -> str:
    started = time.perf_counter()
    state = readiness(settings)
    if not state.transcription_ready:
        raise VoiceError(state.transcription_detail)

    with tempfile.TemporaryDirectory(prefix="atlas-voice-") as directory:
        root = Path(directory)
        source = root / "recording"
        wave = root / "recording.wav"
        output = root / "transcript"
        source.write_bytes(recording)

        _run(
            [
                _executable(settings.voice_ffmpeg_cli) or settings.voice_ffmpeg_cli,
                "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                # Browser audio containers only: reject playlists and network protocols.
                "-protocol_whitelist", "file",
                "-format_whitelist", "matroska,webm,mov,ogg,wav,mp3",
                "-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn",
                "-t", "61", "-ar", "16000", "-ac", "1",
                "-c:a", "pcm_s16le", str(wave),
            ],
            settings.voice_timeout,
        )
        _trim_silence(wave)
        converted = time.perf_counter()
        # CPU mode is predictable across deployments and avoids Metal/CUDA
        # driver mismatches in an optional interface; the base model remains
        # quick enough for short questions.
        command = [
            _executable(settings.voice_whisper_cli) or settings.voice_whisper_cli,
            "-m", str(_path(settings.voice_whisper_model)),
            "-f", str(wave), "-otxt", "-of", str(output), "-nt", "-np", "-ng",
            "-bs", "1", "-bo", "1", "-nf", "-t", str(settings.voice_whisper_threads),
        ]
        language = voice_preferences.language(settings).strip()
        if language:
            command.extend(["-l", language])
        _run(command, settings.voice_timeout)
        log.info(
            "Local transcription: convert %.0f ms, decode %.0f ms, total %.0f ms",
            (converted - started) * 1000,
            (time.perf_counter() - converted) * 1000,
            (time.perf_counter() - started) * 1000,
        )

        transcript_path = output.with_suffix(".txt")
        text = (
            transcript_path.read_text(encoding="utf-8").strip()
            if transcript_path.exists()
            else ""
        )
        if not text:
            raise VoiceError("No speech was detected. Try again closer to the microphone.")
        return " ".join(text.split())


def _trim_silence(path: Path) -> None:
    """Trim quiet edges; reject silence before sending it to a generative decoder."""
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        samples = array("h", source.readframes(source.getnframes()))
    if len(samples) > rate * 60:
        raise VoiceError("Keep recordings under one minute.")
    block = rate // 50  # 20 ms windows; retain 200 ms around speech.
    active = [
        start for start in range(0, len(samples), block)
        if sum(abs(v) for v in samples[start:start + block]) / block > 80
    ]
    if not active:
        raise VoiceError("No speech was detected. Try again closer to the microphone.")
    first = max(0, active[0] - rate // 5)
    last = min(len(samples), active[-1] + block + rate // 5)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples[first:last].tobytes())


def synthesize(text: str, settings: Settings, voice_id: str | None = None) -> bytes:
    state = readiness(settings)
    if not state.synthesis_ready:
        raise VoiceError(state.synthesis_detail)
    selected = voice_id if voice_id is not None else voice_preferences.selected(settings)
    model = voice_preferences.installed(settings).get(selected)
    if model is None:
        raise VoiceError("This voice is no longer installed. Choose another in AI Models.")
    try:
        return voice_synthesis.render(text, model)
    except ImportError:
        pass  # A separately installed Piper CLI remains a supported fallback.
    except Exception as exc:
        log.warning("Local speech synthesis failed: %s", exc)
        raise VoiceError("Local speech failed. Check the voice model and try again.") from exc

    with tempfile.TemporaryDirectory(prefix="atlas-voice-") as directory:
        root = Path(directory)
        output = root / "answer.wav"
        prompt = root / "answer.txt"
        prompt.write_text(text, encoding="utf-8")
        _run(
            [
                _executable(settings.voice_piper_cli) or settings.voice_piper_cli,
                "-m", str(model),
                "-i", str(prompt), "-f", str(output),
            ],
            settings.voice_timeout,
        )
        if not output.exists() or output.stat().st_size == 0:
            raise VoiceError("Piper did not produce an audio file.")
        return output.read_bytes()
