"""Keep one Piper voice warm rather than reloading Python/ONNX per sentence."""

import io
import json
import threading
import wave
from functools import lru_cache
from pathlib import Path

_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load(path: str, modified: int, config_modified: int):
    import onnxruntime
    from piper.config import PiperConfig
    from piper.voice import PiperVoice

    onnxruntime.disable_telemetry_events()
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    with open(f"{path}.json", encoding="utf-8") as file:
        config = PiperConfig.from_dict(json.load(file))
    return PiperVoice(
        config=config,
        session=onnxruntime.InferenceSession(
            path, sess_options=options, providers=["CPUExecutionProvider"]
        ),
        use_tashkeel=False,
    )


def render(text: str, path: Path) -> bytes:
    # Piper's phonemizer and the cached voice are shared; don't allow an
    # unbounded number of competing CPU jobs from double clicks.
    if not _lock.acquire(timeout=5):
        raise RuntimeError("Local speech is busy. Try again in a moment.")
    try:
        voice = _load(
            str(path), path.stat().st_mtime_ns, Path(f"{path}.json").stat().st_mtime_ns
        )
        result = io.BytesIO()
        with wave.open(result, "wb") as output:
            voice.synthesize_wav(text, output)
        return result.getvalue()
    finally:
        _lock.release()
