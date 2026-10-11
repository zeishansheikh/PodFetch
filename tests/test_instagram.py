"""
Tests for Instagram Trending Audio discovery, filtering, deduplication,
download, companion metadata, manifest generation, and Google Drive upload.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from audio_manifest import AudioManifestManager
from config import AppConfig
from database import Database, VideoStatus
from drive_uploader import GoogleDriveUploader
from filters import VideoCandidate, VideoFilter
from instagram_discovery import (
    InstagramAudioDiscoverer,
    InstagramAudioMetadata,
    normalize_meta_base_url,
)
from instagram_downloader import InstagramAudioDownloader, InstagramDownloadError
from main import execute_pipeline


@pytest.fixture
def test_config(tmp_path: Path) -> AppConfig:
    db_file = tmp_path / "test_instagram.db"
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / "audio_manifest.json"

    return AppConfig(
        database_path=db_file,
        temp_dir=temp_dir,
        log_dir=log_dir,
        enabled_sources=["instagram"],
        instagram_enabled=True,
        youtube_enabled=False,
        pinterest_enabled=False,
        instagram_access_token="test_mock_token_12345",
        instagram_account_id="17841400000000000",
        instagram_audio_manifest_path=manifest_path,
        min_audio_duration_seconds=5,
        max_audio_duration_seconds=420,
        google_drive_folder_id="mock_drive_folder_id",
        dry_run=False,
    )


@pytest.fixture
def test_db(test_config: AppConfig) -> Database:
    return Database(test_config.database_path)


def test_instagram_discovery_missing_credentials_limitation(tmp_path: Path):
    """Verify that missing credentials report exact limitation and do not fabricate data."""
    config = AppConfig(
        database_path=tmp_path / "test.db",
        temp_dir=tmp_path / "temp",
        instagram_access_token=None,
        instagram_account_id=None,
    )
    db = Database(config.database_path)
    discoverer = InstagramAudioDiscoverer(config, db)

    is_available, limitation = discoverer.check_api_availability()
    assert is_available is False
    assert limitation is not None
    assert "INSTAGRAM_ACCESS_TOKEN is not configured" in limitation

    candidates, examined, skipped, limitations = discoverer.discover_trending_audio()
    assert candidates == []
    assert examined == 0
    assert len(limitations) > 0
    assert "INSTAGRAM_ACCESS_TOKEN is not configured" in limitations[0]


def test_instagram_discovery_api_success(test_config: AppConfig, test_db: Database):
    """Verify successful discovery and parsing of trending audio via Meta Graph API."""
    discoverer = InstagramAudioDiscoverer(test_config, test_db)

    mock_api_payload = {
        "data": [
            {
                "id": "audio_101",
                "title": "Aesthetic Sunset Beats",
                "artist_name": "Lofi Producer",
                "audio_src": "https://cdn.instagram.com/audio/101.mp3",
                "duration": 30,
                "reel_count": 85000,
                "trend_rank": 1,
                "is_authorized": True,
                "permalink": "https://www.instagram.com/reels/audio/audio_101/",
                "created_time": "2026-10-10T12:00:00Z",
            },
            {
                "id": "audio_102",
                "title": "Restricted Track",
                "artist_name": "Major Label",
                "audio_src": None,
                "duration": 45,
                "reel_count": 12000,
                "trend_rank": 2,
                "is_authorized": False,
                "permalink": "https://www.instagram.com/reels/audio/audio_102/",
                "created_time": "2026-10-10T13:00:00Z",
            },
        ]
    }

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_api_payload
        mock_get.return_value = mock_resp

        candidates, examined, skipped, limitations = discoverer.discover_trending_audio(limit=5)

        assert examined == 2
        assert len(candidates) == 2
        assert limitations == []

        cand1 = candidates[0]
        assert cand1.platform == "instagram"
        assert cand1.source_id == "audio_101"
        assert cand1.title == "Aesthetic Sunset Beats"
        assert cand1.artist == "Lofi Producer"
        assert cand1.audio_url == "https://cdn.instagram.com/audio/101.mp3"
        assert cand1.reel_count == 85000
        assert cand1.trend_rank == 1
        assert cand1.is_authorized is True
        assert cand1.popularity_score is not None

        cand2 = candidates[1]
        assert cand2.source_id == "audio_102"
        assert cand2.is_authorized is False
        assert cand2.audio_url is None


def test_instagram_discovery_api_permission_error_reporting(test_config: AppConfig, test_db: Database):
    """Verify exact reporting when Meta Graph API returns 403 Forbidden with permission details."""
    discoverer = InstagramAudioDiscoverer(test_config, test_db)

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {
            "error": {
                "message": "(#10) Application does not have permission for this action",
                "type": "OAuthException",
                "code": 10,
            }
        }
        mock_get.return_value = mock_resp

        candidates, examined, skipped, limitations = discoverer.discover_trending_audio()
        assert candidates == []
        assert examined == 0
        assert len(limitations) == 1
        assert "HTTP 403" in limitations[0]
        assert "OAuthException code 10" in limitations[0]


def test_instagram_filtering_and_deduplication(test_config: AppConfig, test_db: Database):
    """Verify that unauthorized tracks, missing streams, and DB duplicates are filtered out."""
    vfilter = VideoFilter(test_config, test_db)

    # 1. Valid candidate
    valid_cand = VideoCandidate(
        youtube_video_id="",
        channel_id="Artist A",
        channel_name="Artist A",
        title="Valid Trending Audio",
        youtube_url="https://instagram.com/audio/1",
        platform="instagram",
        source_id="track_valid",
        canonical_url="https://instagram.com/audio/1",
        duration_seconds=25,
        media_type="audio",
        artist="Artist A",
        audio_url="https://cdn.instagram.com/audio/1.mp3",
        is_authorized=True,
    )
    is_ok, reason = vfilter.evaluate_candidate(valid_cand)
    assert is_ok is True
    assert reason is None

    # 2. Unauthorized track
    unauth_cand = VideoCandidate(
        youtube_video_id="",
        channel_id="Artist B",
        channel_name="Artist B",
        title="Unauthorized Audio",
        youtube_url="https://instagram.com/audio/2",
        platform="instagram",
        source_id="track_unauth",
        canonical_url="https://instagram.com/audio/2",
        duration_seconds=25,
        media_type="audio",
        artist="Artist B",
        audio_url="https://cdn.instagram.com/audio/2.mp3",
        is_authorized=False,
    )
    is_ok, reason = vfilter.evaluate_candidate(unauth_cand)
    assert is_ok is False
    assert "not authorized" in reason

    # 3. Missing audio download URL
    no_stream_cand = VideoCandidate(
        youtube_video_id="",
        channel_id="Artist C",
        channel_name="Artist C",
        title="No Stream Audio",
        youtube_url="https://instagram.com/audio/3",
        platform="instagram",
        source_id="track_no_stream",
        canonical_url="https://instagram.com/audio/3",
        duration_seconds=25,
        media_type="audio",
        artist="Artist C",
        audio_url=None,
        is_authorized=True,
    )
    is_ok, reason = vfilter.evaluate_candidate(no_stream_cand)
    assert is_ok is False
    assert "No downloadable audio stream URL" in reason

    # 4. Deduplication: Insert into DB as UPLOADED
    test_db.upsert_video(
        source_id="track_valid",
        title="Valid Trending Audio",
        platform="instagram",
        status=VideoStatus.UPLOADED,
    )
    assert test_db.is_video_processed("track_valid", platform="instagram") is True

    # Re-evaluate valid_cand: should now be rejected as duplicate
    is_ok, reason = vfilter.evaluate_candidate(valid_cand)
    assert is_ok is False
    assert "Already processed" in reason


def test_instagram_audio_downloader_and_companion_metadata(test_config: AppConfig):
    """Verify downloading authorized audio stream and generating companion metadata JSON."""
    downloader = InstagramAudioDownloader(test_config)

    candidate = VideoCandidate(
        youtube_video_id="",
        channel_id="Nature Beats",
        channel_name="Nature Beats",
        title="Morning Forest Whispers",
        youtube_url="https://instagram.com/audio/track_dl",
        platform="instagram",
        source_id="track_dl",
        canonical_url="https://instagram.com/audio/track_dl",
        duration_seconds=20,
        media_type="audio",
        artist="Nature Beats",
        audio_url="https://cdn.instagram.com/audio/mock_download.mp3",
        reel_count=45000,
        trend_rank=3,
        popularity_score=88.5,
        is_authorized=True,
    )

    # Valid MP3 file content with ID3 header
    fake_audio_bytes = b"ID3\x03\x00\x00\x00\x00\x00#TIT2\x00\x00\x00\x08\x00\x00\x00Morning" + (b"\xff\xfb\x90d" * 300)

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [fake_audio_bytes]
        mock_get.return_value.__enter__.return_value = mock_resp

        audio_path, meta_path = downloader.download_audio(candidate)

        assert audio_path.exists()
        assert audio_path.suffix == ".mp3"
        assert meta_path.exists()
        assert meta_path.suffix == ".json"

        # Check metadata JSON content
        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta_data["platform"] == "instagram"
        assert meta_data["audio_id"] == "track_dl"
        assert meta_data["title"] == "Morning Forest Whispers"
        assert meta_data["artist"] == "Nature Beats"
        assert meta_data["popularity"]["reel_count"] == 45000
        assert meta_data["popularity"]["trend_rank"] == 3
        assert meta_data["is_authorized"] is True

        # Cleanup
        downloader.cleanup_files(audio_path, meta_path)
        assert not audio_path.exists()
        assert not meta_path.exists()


def test_instagram_audio_downloader_unauthorized_rejection(test_config: AppConfig):
    """Verify that attempting to download unauthorized track raises InstagramDownloadError."""
    downloader = InstagramAudioDownloader(test_config)

    unauthorized_cand = VideoCandidate(
        youtube_video_id="",
        channel_id="Label",
        channel_name="Label",
        title="Unauthorized Audio",
        youtube_url="https://instagram.com/audio/unauth",
        platform="instagram",
        source_id="unauth",
        canonical_url="https://instagram.com/audio/unauth",
        audio_url="https://cdn.example.com/unauth.mp3",
        is_authorized=False,
    )

    with pytest.raises(InstagramDownloadError) as exc_info:
        downloader.download_audio(unauthorized_cand)
    assert "unauthorized" in str(exc_info.value).lower()


def test_audio_manifest_manager_persistence(tmp_path: Path):
    """Verify AudioManifestManager adds tracks and atomically updates audio_manifest.json."""
    manifest_file = tmp_path / "audio_manifest.json"
    manager = AudioManifestManager(manifest_file)

    initial_data = manager.load_manifest()
    assert initial_data["total_tracks"] == 0
    assert initial_data["tracks"] == []

    # Add first track
    track = manager.add_or_update_track(
        audio_id="ig_100",
        title="Zen Meditation",
        artist="Lotus",
        source_url="https://instagram.com/audio/ig_100",
        duration_seconds=30,
        popularity={"reel_count": 50000, "trend_rank": 1, "popularity_score": 95.0},
        is_authorized=True,
        audio_file="instagram_lotus_ig_100.mp3",
        local_path=str(tmp_path / "instagram_lotus_ig_100.mp3"),
        drive_file_id="drive_id_100",
        drive_path="mock_folder/instagram/2026-10-11/instagram_lotus_ig_100.mp3",
        status="UPLOADED",
    )

    assert track["audio_id"] == "ig_100"
    assert manifest_file.exists()

    # Reload from disk
    reloaded = manager.load_manifest()
    assert reloaded["total_tracks"] == 1
    assert reloaded["tracks"][0]["title"] == "Zen Meditation"
    assert reloaded["tracks"][0]["drive_file_id"] == "drive_id_100"

    available = manager.get_available_tracks()
    assert len(available) == 1
    assert available[0]["audio_id"] == "ig_100"


def test_drive_uploader_instagram_isolation_and_mimetypes(test_config: AppConfig, tmp_path: Path):
    """Verify Drive uploader places Instagram files into isolated instagram/ subfolder and detects mimetypes."""
    uploader = GoogleDriveUploader(test_config)

    fake_mp3 = tmp_path / "test_track.mp3"
    fake_mp3.write_bytes(b"mock mp3 data")
    fake_json = tmp_path / "test_track.json"
    fake_json.write_text('{"audio_id": "test"}', encoding="utf-8")

    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_service.files.return_value = mock_files

    # Mock get_or_create_subfolder and check_file_exists
    with patch.object(uploader, "authenticate", return_value=mock_service), \
         patch.object(uploader, "get_or_create_subfolder", return_value=("subfolder_ig_id", "instagram")), \
         patch.object(uploader, "get_or_create_date_subfolder", return_value=("date_id", "2026-10-11")), \
         patch.object(uploader, "check_file_exists", return_value=None):

        mock_request = MagicMock()
        mock_request.next_chunk.return_value = (None, {"id": "uploaded_mp3_id"})
        mock_files.create.return_value = mock_request

        file_id, drive_path = uploader.upload_file(
            file_path=fake_mp3,
            custom_filename="test_track.mp3",
            platform="instagram",
        )

        assert file_id == "uploaded_mp3_id"
        assert "instagram" in drive_path

        # Verify MIME type passed to MediaFileUpload was audio/mpeg
        call_args = mock_files.create.call_args
        media_body = call_args[1]["media_body"]
        assert media_body.mimetype() == "audio/mpeg"

        # Now upload companion JSON
        mock_request.next_chunk.return_value = (None, {"id": "uploaded_json_id"})
        json_file_id, json_drive_path = uploader.upload_file(
            file_path=fake_json,
            custom_filename="test_track.json",
            platform="instagram",
        )
        assert json_file_id == "uploaded_json_id"
        call_args_json = mock_files.create.call_args
        json_media_body = call_args_json[1]["media_body"]
        assert json_media_body.mimetype() == "application/json"


def test_pipeline_with_instagram_trending_audio(test_config: AppConfig, test_db: Database, tmp_path: Path):
    """End-to-end integration test of execute_pipeline with Instagram source."""
    cand = VideoCandidate(
        youtube_video_id="",
        channel_id="Wave Music",
        channel_name="Wave Music",
        title="Sunset Chill Vibes",
        youtube_url="https://instagram.com/reels/audio/track_e2e/",
        platform="instagram",
        source_id="track_e2e",
        canonical_url="https://instagram.com/reels/audio/track_e2e/",
        duration_seconds=22,
        media_type="audio",
        artist="Wave Music",
        audio_url="https://cdn.instagram.com/audio/track_e2e.mp3",
        reel_count=50000,
        trend_rank=1,
        popularity_score=92.0,
        is_authorized=True,
    )

    with patch("main.InstagramAudioDiscoverer") as mock_disc_cls, \
         patch("main.InstagramAudioDownloader") as mock_dl_cls, \
         patch("main.GoogleDriveUploader") as mock_uploader_cls:

        mock_disc = MagicMock()
        mock_disc.discover_trending_audio.return_value = ([cand], 1, 0, [])
        mock_disc_cls.return_value = mock_disc

        fake_audio = tmp_path / "track_e2e.mp3"
        fake_audio.write_bytes(b"audio data")
        fake_meta = tmp_path / "track_e2e.json"
        fake_meta.write_text("{}", encoding="utf-8")

        mock_dl = MagicMock()
        mock_dl.download_audio.return_value = (fake_audio, fake_meta)
        mock_dl_cls.return_value = mock_dl

        mock_uploader = MagicMock()
        mock_uploader.upload_file.side_effect = [
            ("drive_audio_789", "drive/instagram/track_e2e.mp3"),
            ("drive_meta_789", "drive/instagram/track_e2e.json"),
        ]
        mock_uploader_cls.return_value = mock_uploader

        exit_code = execute_pipeline(test_config, cli_source="instagram", cli_limit=1)
        assert exit_code == 0

        # Verify SQLite DB
        record = test_db.get_video("track_e2e", platform="instagram")
        assert record is not None
        assert record["status"] == VideoStatus.UPLOADED
        assert record["drive_file_id"] == "drive_audio_789"

        # Verify Manifest
        manifest_mgr = AudioManifestManager(test_config.instagram_audio_manifest_path)
        manifest_track = manifest_mgr.get_track("track_e2e")
        assert manifest_track is not None
        assert manifest_track["title"] == "Sunset Chill Vibes"
        assert manifest_track["artist"] == "Wave Music"
        assert manifest_track["drive_file_id"] == "drive_audio_789"
        assert manifest_track["metadata_drive_file_id"] == "drive_meta_789"


def test_normalize_meta_base_url():
    """Verify endpoint URL normalization for Meta Graph API."""
    assert normalize_meta_base_url("https://facebook.com") == "https://graph.facebook.com/v21.0"
    assert normalize_meta_base_url("https://facebook.com/") == "https://graph.facebook.com/v21.0"
    assert normalize_meta_base_url("https://graph.facebook.com/v21.0") == "https://graph.facebook.com/v21.0"
    assert normalize_meta_base_url("https://graph.facebook.com") == "https://graph.facebook.com/v21.0"
    assert normalize_meta_base_url(None) == "https://graph.facebook.com/v21.0"
    assert normalize_meta_base_url("") == "https://graph.facebook.com/v21.0"


def test_instagram_discovery_ig_audio_endpoint_success(test_config: AppConfig, test_db: Database):
    """Verify official Meta /ig_audio response parsing and track detail endpoint resolution."""
    discoverer = InstagramAudioDiscoverer(test_config, test_db)

    mock_list_payload = {
        "audio": [
            {
                "audio_id": "28620968620889095",
                "duration_in_ms": 17000,
                "title": "Original audio",
                "audio_type": "original_sound",
                "on_platform_audio_preview_link": "https://www.instagram.com/reels/audio/28620968620889095/",
                "ig_username": "_zuber.04",
            }
        ]
    }

    mock_detail_payload = {
        "audio_id": "28620968620889095",
        "duration_in_ms": 17000,
        "title": "Original audio",
        "download_url": "https://cdn.example.com/audio/28620968620889095.mp4",
        "display_artist": "Zuber Official",
    }

    with patch("requests.get") as mock_get:
        resp_list = MagicMock()
        resp_list.status_code = 200
        resp_list.json.return_value = mock_list_payload

        resp_detail = MagicMock()
        resp_detail.status_code = 200
        resp_detail.json.return_value = mock_detail_payload

        mock_get.side_effect = [resp_list, resp_detail]

        candidates, examined, skipped, limitations = discoverer.discover_trending_audio(limit=5)

        assert examined == 1
        assert len(candidates) == 1
        assert limitations == []

        cand = candidates[0]
        assert cand.platform == "instagram"
        assert cand.source_id == "28620968620889095"
        assert cand.title == "Original audio"
        assert cand.artist in ("Zuber Official", "_zuber.04")
        assert cand.audio_url == "https://cdn.example.com/audio/28620968620889095.mp4"
        assert cand.duration_seconds == 17
        assert cand.canonical_url == "https://www.instagram.com/reels/audio/28620968620889095/"
        assert cand.is_authorized is True


def test_instagram_poetry_voiceover_filter_rejection(test_config: AppConfig, test_db: Database):
    """Verify that user voiceovers, poetry, and reel audio without official songs are rejected."""
    vfilter = VideoFilter(test_config, test_db)

    # 1. 'Original audio' voiceover reel
    poetry_cand = VideoCandidate(
        youtube_video_id="",
        channel_id="_zuber.04",
        channel_name="_zuber.04",
        title="Original audio",
        youtube_url="https://instagram.com/audio/voiceover_1",
        platform="instagram",
        source_id="voiceover_1",
        canonical_url="https://instagram.com/audio/voiceover_1",
        duration_seconds=17,
        media_type="audio",
        artist="_zuber.04",
        audio_url="https://cdn.example.com/voiceover.mp3",
        is_authorized=True,
    )
    is_ok, reason = vfilter.evaluate_candidate(poetry_cand)
    assert is_ok is False
    assert "voiceover/poetry" in reason

    # 2. Genuine official song track
    song_cand = VideoCandidate(
        youtube_video_id="",
        channel_id="Talha Anjum",
        channel_name="Talha Anjum",
        title="Told My Brother",
        youtube_url="https://instagram.com/audio/song_1",
        platform="instagram",
        source_id="song_1",
        canonical_url="https://instagram.com/audio/song_1",
        duration_seconds=216,
        media_type="audio",
        artist="Talha Anjum, Umair",
        audio_url="ytsearch1:Told My Brother Talha Anjum, Umair official audio",
        is_authorized=True,
    )
    is_ok, reason = vfilter.evaluate_candidate(song_cand)
    assert is_ok is True
    assert reason is None


