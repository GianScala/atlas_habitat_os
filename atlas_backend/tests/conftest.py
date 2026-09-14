"""Shared fixtures.

Every test that touches storage gets its own throwaway database file, so the
suite never reads or writes the real chat history.
"""

# Pin the suite to its own reference habitat, BEFORE any app module is imported.
#
# The suite asserts habitat-specific behaviour (resources, zones, units, the
# meter round), so it needs a habitat — but tying it to a habitat somebody
# actually ships would mean an example could not be edited without breaking
# tests, and a developer's own .env could change the result. `tests/fixtures/
# reference_habitat.yaml` is a fictional station that belongs to the suite.
#
# Environment variables beat the .env file in pydantic-settings, so this wins.
# It is set at import time because habitat-derived module constants (RESOURCES,
# ZONE_NAMES, ...) resolve when their modules are first imported.
import atexit
import os
import tempfile
from pathlib import Path

os.environ["HABITAT_CONFIG"] = str(
    Path(__file__).resolve().parent / "fixtures" / "reference_habitat.yaml"
)

import pytest  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402

# Never load a developer's private .env or external connection configuration.
Settings.model_config["env_file"] = None
for key in list(os.environ):
    if key.lower() in Settings.model_fields and key.upper() != "HABITAT_CONFIG":
        del os.environ[key]
_test_state = tempfile.TemporaryDirectory(prefix="atlas-tests-")
atexit.register(_test_state.cleanup)
os.environ["DATABASE_PATH"] = str(Path(_test_state.name) / "state.db")
os.environ["KNOWLEDGE_DIR"] = str(Path(_test_state.name) / "knowledge")
os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
get_settings.cache_clear()
from app.storage.database import initialise  # noqa: E402


@pytest.fixture()
def temp_database(tmp_path, monkeypatch):
    """Point the app at an empty database for the duration of one test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "test.db"))
    initialise()
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """An offline suite must never contact a real habitat or model provider."""
    import socket

    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in unit tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
