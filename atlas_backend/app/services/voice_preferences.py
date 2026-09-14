"""Choose only installed local voices; request fields are never file paths."""

import json
import sqlite3
import time
from pathlib import Path

from app.config import Settings
from app.core.errors import QueryError
from app.storage.database import connect


def installed(settings: Settings) -> dict[str, Path]:
    root = Path(__file__).resolve().parents[2]
    default = Path(settings.voice_piper_model).expanduser()
    if not default.is_absolute():
        default = root / default
    candidates = sorted((root / "models").glob("*.onnx"))
    if settings.voice_piper_model:
        candidates.append(default)
    result = {}
    for path in candidates:
        config = Path(f"{path}.json")
        if not path.is_file() or not config.is_file():
            continue
        try:
            metadata = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # Other Piper phonemizers may download auxiliary models at runtime.
        # Only the bundled, offline eSpeak path is offered here.
        if metadata.get("phoneme_type") == "espeak":
            result[path.stem] = path.resolve()
    return result


def stored() -> dict[str, str]:
    try:
        with connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM app_settings WHERE key IN ('voice', 'voice_language')"
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}
    except sqlite3.OperationalError:
        return {}


def selected(settings: Settings) -> str:
    voices = installed(settings)
    saved = stored().get("voice", "")
    default = Path(settings.voice_piper_model).stem
    if saved in voices:
        return saved
    return default if default in voices else next(iter(voices), "")


def label(key: str) -> str:
    parts = key.split("-")
    if len(parts) == 3:
        locale, name, quality = parts
        return f"{name.title()} · {locale.replace('_', '-')} · {quality}"
    return key


def language(settings: Settings) -> str:
    return stored().get("voice_language") or settings.voice_whisper_language


def choose(voice_id: str, language_id: str, settings: Settings) -> None:
    if voice_id not in installed(settings):
        raise QueryError("Choose an installed local voice.")
    with connect() as connection:
        connection.executemany(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            [("voice", voice_id, time.time()), ("voice_language", language_id, time.time())],
        )
