"""Check privacy guard behavior without staging any actual sensitive files."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "release_guard", Path(__file__).resolve().parents[2] / "scripts/check_release.py"
)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def test_private_data_paths_are_refused():
    for path in (".env.production", "atlas_backend/knowledge/document.md",
                 "atlas_backend/config/private/habitat.yaml", "dump.sqlite3",
                 "backup.db-wal", "telemetry.csv", "atlas_backend/:memory:.ses",
                 "recording.wav", "atlas_backend/models/voice.onnx.json"):
        assert guard.check(path, b"synthetic"), path


def test_templates_and_knowledge_source_are_allowed():
    for path in ("atlas_backend/.env.example", "atlas_backend/app/knowledge/store.py"):
        assert not guard.check(path, b"# generic example")


def test_private_habitat_reference_in_fixture_is_refused():
    assert guard.check("tests/fixture.yaml", b"name: " + b"Luna" + b"res")


def test_credential_in_source_is_refused():
    assert guard.check("app/config.py", b"token = '" + b"sk-ant-" + b"x" * 30 + b"'")
