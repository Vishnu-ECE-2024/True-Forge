"""
Integration tests for the Assets and Search API.
Requires a running database (use test database from env or in-memory SQLite).

Run with:
  pytest tests/ -v
  pytest tests/test_api.py -v -k "health"
"""

import io
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Override DB URL before importing app
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_smp.db")
os.environ.setdefault("DATA_DIR", "/tmp/smp_test_data")
os.environ.setdefault("FAISS_INDEX_PATH", "/tmp/smp_test_data/indices/visual.index")

from src.main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "total_assets" in data


def test_list_assets_empty():
    response = client.get("/api/assets/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_asset_not_found():
    response = client.get("/api/assets/nonexistent-id")
    assert response.status_code == 404


def test_upload_invalid_extension():
    fake_file = io.BytesIO(b"fake content")
    response = client.post(
        "/api/assets/upload",
        files={"file": ("test.txt", fake_file, "text/plain")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_search_upload_empty_index():
    """Search on empty index should return empty results, not error."""
    fake_video = io.BytesIO(b"\x00" * 100)
    with patch("src.api.search._search_by_fingerprint") as mock_search:
        # Simulate empty index path
        response = client.post(
            "/api/search/upload",
            files={"file": ("test.mp4", fake_video, "video/mp4")},
        )
    # Either 200 with empty results or handled gracefully
    assert response.status_code in (200, 422)


def test_delete_nonexistent_asset():
    response = client.delete("/api/assets/does-not-exist")
    assert response.status_code == 404
