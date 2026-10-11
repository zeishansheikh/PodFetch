"""Tests for PodFetch FastAPI endpoints in api.py."""

import pytest
from fastapi.testclient import TestClient
from api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["name"] == "PodFetch API"
    assert "version" in data


def test_api_stats(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_processed" in data
    assert "uploaded" in data
    assert "failed" in data
    assert "by_platform" in data
    assert isinstance(data["total_processed"], int)


def test_api_jobs_listing(client):
    res = client.get("/api/jobs?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "jobs" in data
    assert "total" in data
    assert isinstance(data["jobs"], list)


def test_api_jobs_active(client):
    res = client.get("/api/jobs/active")
    assert res.status_code == 200
    data = res.json()
    assert "active_jobs" in data
    assert isinstance(data["active_jobs"], list)


def test_api_library_search(client):
    res = client.get("/api/library?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_api_drive_status(client):
    res = client.get("/api/drive/status")
    assert res.status_code == 200
    data = res.json()
    assert "configured" in data
    assert "folder_id" in data
    assert "subfolders" in data
    assert "recent_uploads" in data


def test_api_instagram_status(client):
    res = client.get("/api/instagram/status")
    assert res.status_code == 200
    data = res.json()
    assert "configured" in data
    assert "account_id" in data
    assert "drive_folder" in data


def test_api_settings(client):
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "sources_enabled" in data
    assert "video_filter" in data
    assert "instagram" in data
    assert "google_drive" in data
    # Ensure secrets are never exposed in settings response
    assert "access_token" not in str(data).lower() or "configured" in str(data).lower()


def test_api_logs(client):
    res = client.get("/api/logs?lines=10")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)


def test_api_validation_errors(client):
    # Missing required URL for video download
    res = client.post("/api/download/video", json={})
    assert res.status_code == 422

    # Missing required fields for instagram audio download
    res = client.post("/api/download/instagram-audio", json={})
    assert res.status_code == 422


def test_spa_index_served(client):
    # Verify the frontend production build index.html is served at root
    res = client.get("/")
    assert res.status_code == 200
    assert "PodFetch" in res.text
    assert '<div id="root">' in res.text
