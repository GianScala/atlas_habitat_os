"""Regression tests for release hardening; all inputs are synthetic."""

import io

import pytest
from fastapi import HTTPException, UploadFile

from app.api.routes import connectors
from app.config import get_settings
from app.core.errors import DatasourceError
from app.datasource.wire import assert_read_only


@pytest.mark.parametrize("query", [
    "SELECT value INTO\tcopy FROM readings",
    "SELECT value\rINTO copy FROM readings",
    "SELECT value /* comment */ INTO copy FROM readings",
    "SELECTED value FROM readings",
    "SHOW measurements; DROP DATABASE example",
    "DROP DATABASE example",
])
def test_influx_write_bypasses_are_rejected(query):
    with pytest.raises(DatasourceError):
        assert_read_only(query)


@pytest.mark.parametrize("query", ["SELECT value FROM readings", "\nSHOW MEASUREMENTS"])
def test_influx_reads_remain_available(query):
    assert_read_only(query)


def test_upload_rejected_before_indexing(monkeypatch):
    import asyncio

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    monkeypatch.setattr(
        connectors.store, "add", lambda *args: pytest.fail("indexed oversized file")
    )
    stream = io.BytesIO(b"x" * (1024 * 1024 + 2))
    upload = UploadFile(filename="synthetic.txt", file=stream)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(connectors.upload_document(upload))
    assert exc.value.status_code == 413
    assert stream.closed


def test_foreign_browser_writes_are_blocked():
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    response = client.post('/api/models/remove', json={"name": "example"},
                           headers={"Origin": "https://foreign.example"})
    assert response.status_code == 403


def test_untrusted_host_is_blocked():
    from fastapi.testclient import TestClient

    from app.main import create_app

    response = TestClient(create_app()).get('/api/health', headers={"Host": "foreign.example"})
    assert response.status_code == 400


def test_body_limit_precedes_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    response = TestClient(create_app()).post(
        '/api/connectors/documents', content=b'x' * (2 * 1024 * 1024 + 1),
        headers={"Content-Type": "multipart/form-data; boundary=example"},
    )
    assert response.status_code == 413


def test_document_lifecycle_uses_local_storage(temp_database, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.knowledge import search
    from app.main import create_app

    monkeypatch.setattr(get_settings(), "knowledge_dir", str(tmp_path / "documents"))
    monkeypatch.setattr(
        connectors.embed, "available", lambda: (False, "Synthetic offline test")
    )
    monkeypatch.setattr(connectors.embed, "embed", lambda texts: [])
    monkeypatch.setattr(connectors.embed, "embed_one", lambda text: None)
    client = TestClient(create_app())
    content = (
        b"Synthetic training procedure: inspect the demonstration filter each morning. "
        b"Record the fictional filter status on the practice checklist before continuing."
    )
    uploaded = client.post('/api/connectors/documents', files={
        "file": ("synthetic.txt", content, "text/plain"),
    })
    assert uploaded.status_code == 200
    document = uploaded.json()["documents"][0]
    document_id = document["id"]
    assert search.search("filter checklist")["data"]
    assert client.put(f'/api/connectors/documents/{document_id}',
                      json={"connected": False}).status_code == 200
    assert search.search("filter checklist")["data"] is None
    assert client.delete(f'/api/connectors/documents/{document_id}').status_code == 200
    assert not list((tmp_path / "documents").iterdir())
    assert client.get('/api/connectors/documents').json()["documents"] == []
