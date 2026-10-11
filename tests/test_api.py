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


def test_resolve_video_target_youtube_url():
    from unittest.mock import MagicMock, patch
    from api import _resolve_video_target

    dummy_info = {
        "id": "abc123vid",
        "title": "Test YouTube Video",
        "uploader": "Test Creator",
        "webpage_url": "https://www.youtube.com/watch?v=abc123vid",
        "duration": 180,
        "thumbnail": "https://i.ytimg.com/vi/abc123vid/hqdefault.jpg",
    }
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = dummy_info
        mock_ydl.return_value.__enter__.return_value = mock_instance

        req = _resolve_video_target("https://www.youtube.com/watch?v=abc123vid")
        assert req.platform == "youtube"
        assert req.source_id == "abc123vid"
        assert req.title == "Test YouTube Video"
        assert req.channel_name == "Test Creator"
        assert req.canonical_url == "https://www.youtube.com/watch?v=abc123vid"


def test_resolve_video_target_youtube_keyword():
    from unittest.mock import MagicMock, patch
    from api import _resolve_video_target

    dummy_search = {
        "entries": [{
            "id": "search_vid_99",
            "title": "Search Result Video",
            "uploader": "Channel A",
            "webpage_url": "https://www.youtube.com/watch?v=search_vid_99",
            "duration": 250,
            "thumbnail": "https://example.com/thumb.jpg",
        }]
    }
    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = dummy_search
        mock_ydl.return_value.__enter__.return_value = mock_instance

        req = _resolve_video_target("motivational speech", platform_hint="youtube")
        assert req.platform == "youtube"
        assert req.source_id == "search_vid_99"
        assert req.title == "Search Result Video"
        assert req.search_keyword == "motivational speech"


def test_resolve_video_target_pinterest_url():
    from unittest.mock import MagicMock, patch
    from api import _resolve_video_target

    with patch("api.PinterestDiscoverer") as mock_disc_cls:
        mock_disc = MagicMock()
        mock_disc.fetch_pin_details.return_value = MagicMock(
            title="Aesthetic Nature Pin",
            thumbnail_url="https://example.com/pin.jpg",
            duration_seconds=22,
        )
        mock_disc_cls.return_value = mock_disc

        req = _resolve_video_target("https://www.pinterest.com/pin/9876543210123/")
        assert req.platform == "pinterest"
        assert req.source_id == "9876543210123"
        assert req.canonical_url == "https://www.pinterest.com/pin/9876543210123/"
        assert req.title == "Aesthetic Nature Pin"


def test_resolve_video_target_pinterest_keyword():
    from unittest.mock import MagicMock, patch
    from api import _resolve_video_target
    from pinterest_discovery import PinterestPinMetadata

    fake_pin = PinterestPinMetadata(
        pin_id="112233445566",
        canonical_url="https://www.pinterest.com/pin/112233445566/",
        title="Rain Mood Video",
        description="Rain on window",
        thumbnail_url="https://example.com/rain.jpg",
        is_video=True,
        duration_seconds=15,
        width=1080,
        height=1920,
    )

    with patch("api.PinterestDiscoverer") as mock_disc_cls:
        mock_disc = MagicMock()
        mock_disc.search_keyword.return_value = [fake_pin]
        mock_disc_cls.return_value = mock_disc

        req = _resolve_video_target("rain aesthetics", platform_hint="pinterest")
        assert req.platform == "pinterest"
        assert req.source_id == "112233445566"
        assert req.title == "Rain Mood Video"
        assert req.search_keyword == "rain aesthetics"


def test_api_download_video_endpoint_queues_job(client):
    from unittest.mock import patch
    with patch("api.threading.Thread") as mock_thread:
        res = client.post("/api/download/video", json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "platform": "youtube",
            "title": "Never Gonna Give You Up",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "queued"
        assert "job_id" in data
        assert data["job_id"].startswith("vid-")
        mock_thread.assert_called_once()


def test_api_download_instagram_audio_endpoint_queues_job(client):
    from unittest.mock import patch
    with patch("api.threading.Thread") as mock_thread:
        res = client.post("/api/download/instagram-audio", json={
            "audio_asset_id": "18029384756",
            "title": "Soft Acoustic Melody",
            "artist": "Trending Artist",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "queued"
        assert "job_id" in data
        assert data["job_id"].startswith("audio-")
        mock_thread.assert_called_once()

