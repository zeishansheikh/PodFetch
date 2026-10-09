"""
Integration and unit tests for multi-source (YouTube + Pinterest) pipeline,
candidate selection, database schema migrations, and dry-run execution.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from config import AppConfig
from database import Database, VideoStatus
from discovery import select_multisource_candidates
from filters import VideoCandidate
from main import execute_pipeline


def make_yt_cand(vid: str, ch_id: str, title: str) -> VideoCandidate:
    return VideoCandidate(
        youtube_video_id=vid,
        channel_id=ch_id,
        channel_name=f"Channel {ch_id}",
        title=title,
        youtube_url=f"https://youtube.com/watch?v={vid}",
        platform="youtube",
        source_id=vid,
        duration_seconds=1800,
        published_at=datetime.now(timezone.utc),
    )


def make_pin_cand(
    pin_id: str, title: str, is_vertical: bool = True, kw: str = "nature aesthetic"
) -> VideoCandidate:
    return VideoCandidate(
        youtube_video_id=pin_id,
        channel_id="pinterest",
        channel_name="Pinterest",
        title=title,
        youtube_url=f"https://www.pinterest.com/pin/{pin_id}/",
        platform="pinterest",
        source_id=pin_id,
        search_keyword=kw,
        duration_seconds=20,
        width=1080 if is_vertical else 1920,
        height=1920 if is_vertical else 1080,
    )


def test_select_multisource_candidates_distribution():
    """Verify balanced distribution between YouTube and Pinterest candidates."""
    yt_candidates = [
        make_yt_cand("yt_1", "ch_A", "YT 1"),
        make_yt_cand("yt_2", "ch_B", "YT 2"),
    ]
    pin_candidates = [
        make_pin_cand("pin_1", "Pin 1"),
        make_pin_cand("pin_2", "Pin 2"),
    ]

    selected = select_multisource_candidates(
        candidates_by_source={
            "youtube": yt_candidates,
            "pinterest": pin_candidates,
        },
        min_count=2,
        max_count=2,
        historical_counts={},
        exact_limit=2,
        prefer_vertical=True,
    )

    assert len(selected) == 2
    platforms = {c.platform for c in selected}
    # Should select 1 from each source when balanced
    assert "youtube" in platforms
    assert "pinterest" in platforms


def test_select_multisource_prefers_vertical_pinterest():
    """Verify vertical 9:16 Pinterest candidates are prioritized over non-vertical."""
    pin_horizontal = make_pin_cand("pin_horiz", "Horizontal Pin", is_vertical=False)
    pin_vertical = make_pin_cand("pin_vert", "Vertical Pin", is_vertical=True)

    selected = select_multisource_candidates(
        candidates_by_source={
            "pinterest": [pin_horizontal, pin_vertical],
        },
        min_count=1,
        max_count=1,
        historical_counts={},
        exact_limit=1,
        prefer_vertical=True,
    )

    assert len(selected) == 1
    assert selected[0].source_id == "pin_vert"


def test_database_multisource_uniqueness_and_keyword_preservation(tmp_path: Path):
    """Verify that (platform, source_id) uniqueness works, and duplicate discovery merges keywords."""
    db_file = tmp_path / "multisource.db"
    db = Database(db_file)

    # Insert a YouTube video
    db.upsert_video(
        youtube_video_id="ID_SAME",
        title="YT Same ID",
        youtube_url="https://youtube.com/watch?v=ID_SAME",
        platform="youtube",
        source_id="ID_SAME",
        search_keyword="nature podcast",
    )

    # Insert a Pinterest Pin with the same raw ID (different platform)
    db.upsert_video(
        youtube_video_id="ID_SAME",
        title="Pin Same ID",
        youtube_url="https://www.pinterest.com/pin/ID_SAME/",
        platform="pinterest",
        source_id="ID_SAME",
        search_keyword="nature aesthetic 4k",
    )

    # Both should exist independently
    yt_rec = db.get_video("ID_SAME", platform="youtube")
    pin_rec = db.get_video("ID_SAME", platform="pinterest")
    assert yt_rec is not None
    assert yt_rec["title"] == "YT Same ID"
    assert pin_rec is not None
    assert pin_rec["title"] == "Pin Same ID"

    # Now upsert Pinterest Pin again with another keyword
    db.upsert_video(
        youtube_video_id="ID_SAME",
        title="Pin Same ID Updated",
        youtube_url="https://www.pinterest.com/pin/ID_SAME/",
        platform="pinterest",
        source_id="ID_SAME",
        search_keyword="pink sunset aesthetic",
    )

    updated_pin = db.get_video("ID_SAME", platform="pinterest")
    # Keywords should be combined without duplicating
    assert "nature aesthetic 4k" in updated_pin["search_keyword"]
    assert "pink sunset aesthetic" in updated_pin["search_keyword"]


def test_pipeline_mixed_youtube_and_pinterest(tmp_path: Path):
    """Integration test running execute_pipeline with both YouTube and Pinterest candidates."""
    db_file = tmp_path / "pipeline.db"
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    config = AppConfig(
        database_path=db_file,
        temp_dir=temp_dir,
        log_dir=log_dir,
        enabled_sources=["youtube", "pinterest"],
        youtube_enabled=True,
        pinterest_enabled=True,
        min_videos_per_run=2,
        max_videos_per_run=2,
        google_drive_folder_id="drive_mock_folder",
        dry_run=False,
    )
    db = Database(db_file)

    yt_cand = make_yt_cand("yt_pipe_1", "ch_1", "YT Pipeline Ep")
    pin_cand = make_pin_cand("pin_pipe_1", "Pin Pipeline Clip")

    with patch("main.ChannelDiscoverer") as mock_yt_disc_cls, \
         patch("main.PinterestDiscoverer") as mock_pin_disc_cls, \
         patch("main.VideoDownloader") as mock_yt_dl_cls, \
         patch("main.PinterestDownloader") as mock_pin_dl_cls, \
         patch("main.GoogleDriveUploader") as mock_uploader_cls:

        # Mock YouTube discoverer
        mock_yt_disc = MagicMock()
        mock_yt_disc.collect_and_filter_all_channels.return_value = ({"ch_1": [yt_cand]}, 1, 0)
        mock_yt_disc_cls.return_value = mock_yt_disc

        # Mock Pinterest discoverer (returns 4-tuple: candidates, examined, skipped, errors)
        mock_pin_disc = MagicMock()
        mock_pin_disc.discover_all_keywords.return_value = ([pin_cand], 1, 0, [])
        mock_pin_disc_cls.return_value = mock_pin_disc

        # Mock Downloaders
        mock_yt_dl = MagicMock()
        fake_yt_file = temp_dir / "yt_file.mp4"
        fake_yt_file.write_bytes(b"yt video")
        mock_yt_dl.download_video.return_value = fake_yt_file
        mock_yt_dl_cls.return_value = mock_yt_dl

        mock_pin_dl = MagicMock()
        fake_pin_file = temp_dir / "pin_file.mp4"
        fake_pin_file.write_bytes(b"pin video")
        mock_pin_dl.download_video.return_value = fake_pin_file
        mock_pin_dl_cls.return_value = mock_pin_dl

        # Mock Drive Uploader
        mock_uploader = MagicMock()
        def fake_pipe_upload(local_path, custom_filename=None, **kwargs):
            target = custom_filename or str(local_path)
            if "Pinterest" in target or "pin_pipe_1" in target:
                return ("drive_pin_456", f"drive/{target}")
            return ("drive_yt_123", f"drive/{target}")

        mock_uploader.upload_video.side_effect = fake_pipe_upload
        mock_uploader_cls.return_value = mock_uploader

        exit_code = execute_pipeline(config, cli_limit=2)
        assert exit_code == 0

        # Verify DB records
        yt_record = db.get_video("yt_pipe_1", platform="youtube")
        assert yt_record["status"] == VideoStatus.UPLOADED
        assert yt_record["drive_file_id"] == "drive_yt_123"

        pin_record = db.get_video("pin_pipe_1", platform="pinterest")
        assert pin_record["status"] == VideoStatus.UPLOADED
        assert pin_record["drive_file_id"] == "drive_pin_456"


def test_pipeline_dry_run_never_downloads_or_uploads(tmp_path: Path):
    """Verify that dry-run mode discovers candidates but NEVER downloads or uploads."""
    db_file = tmp_path / "dryrun.db"
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    config = AppConfig(
        database_path=db_file,
        temp_dir=temp_dir,
        log_dir=log_dir,
        enabled_sources=["youtube", "pinterest"],
        youtube_enabled=True,
        pinterest_enabled=True,
        min_videos_per_run=1,
        max_videos_per_run=2,
        dry_run=True,
    )

    yt_cand = make_yt_cand("yt_dry", "ch_1", "YT Dry Ep")
    pin_cand = make_pin_cand("pin_dry", "Pin Dry Clip")

    with patch("main.ChannelDiscoverer") as mock_yt_disc_cls, \
         patch("main.PinterestDiscoverer") as mock_pin_disc_cls, \
         patch("main.VideoDownloader") as mock_yt_dl_cls, \
         patch("main.PinterestDownloader") as mock_pin_dl_cls, \
         patch("main.GoogleDriveUploader") as mock_uploader_cls:

        mock_yt_disc = MagicMock()
        mock_yt_disc.collect_and_filter_all_channels.return_value = ({"ch_1": [yt_cand]}, 1, 0)
        mock_yt_disc_cls.return_value = mock_yt_disc

        mock_pin_disc = MagicMock()
        mock_pin_disc.discover_all_keywords.return_value = ([pin_cand], 1, 0, [])
        mock_pin_disc_cls.return_value = mock_pin_disc

        mock_yt_dl = MagicMock()
        mock_yt_dl_cls.return_value = mock_yt_dl

        mock_pin_dl = MagicMock()
        mock_pin_dl_cls.return_value = mock_pin_dl

        mock_uploader = MagicMock()
        mock_uploader_cls.return_value = mock_uploader

        exit_code = execute_pipeline(config, cli_limit=2)
        assert exit_code == 0

        # Neither downloader nor uploader should have been invoked
        mock_yt_dl.download_video.assert_not_called()
        mock_pin_dl.download_video.assert_not_called()
        mock_uploader.upload_video.assert_not_called()


def test_pipeline_drive_upload_failure_isolation(tmp_path: Path):
    """Verify that Drive upload failure on one item marks it FAILED without stopping the other."""
    db_file = tmp_path / "upload_fail.db"
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    config = AppConfig(
        database_path=db_file,
        temp_dir=temp_dir,
        log_dir=log_dir,
        enabled_sources=["youtube", "pinterest"],
        youtube_enabled=True,
        pinterest_enabled=True,
        google_drive_folder_id="drive_mock_folder",
        dry_run=False,
    )
    db = Database(db_file)

    yt_cand = make_yt_cand("yt_ok", "ch_1", "YT Ok")
    pin_cand = make_pin_cand("pin_fail", "Pin Fail")

    with patch("main.ChannelDiscoverer") as mock_yt_disc_cls, \
         patch("main.PinterestDiscoverer") as mock_pin_disc_cls, \
         patch("main.VideoDownloader") as mock_yt_dl_cls, \
         patch("main.PinterestDownloader") as mock_pin_dl_cls, \
         patch("main.GoogleDriveUploader") as mock_uploader_cls:

        mock_yt_disc = MagicMock()
        mock_yt_disc.collect_and_filter_all_channels.return_value = ({"ch_1": [yt_cand]}, 1, 0)
        mock_yt_disc_cls.return_value = mock_yt_disc

        mock_pin_disc = MagicMock()
        mock_pin_disc.discover_all_keywords.return_value = ([pin_cand], 1, 0, [])
        mock_pin_disc_cls.return_value = mock_pin_disc

        fake_file_1 = temp_dir / "file1.mp4"
        fake_file_1.write_bytes(b"1")
        mock_yt_dl = MagicMock()
        mock_yt_dl.download_video.return_value = fake_file_1
        mock_yt_dl_cls.return_value = mock_yt_dl

        fake_file_2 = temp_dir / "file2.mp4"
        fake_file_2.write_bytes(b"2")
        mock_pin_dl = MagicMock()
        mock_pin_dl.download_video.return_value = fake_file_2
        mock_pin_dl_cls.return_value = mock_pin_dl

        mock_uploader = MagicMock()
        def fake_upload(local_path, custom_filename=None, **kwargs):
            target = custom_filename or str(local_path)
            if "pin_fail" in target:
                raise RuntimeError("Google Drive 503 Service Unavailable")
            return ("drive_ok_id", target)

        mock_uploader.upload_video.side_effect = fake_upload
        mock_uploader_cls.return_value = mock_uploader

        exit_code = execute_pipeline(config, cli_limit=2)
        # Should exit with code 1 because one item failed
        assert exit_code == 1

        # Check DB states
        rec_yt = db.get_video("yt_ok", platform="youtube")
        assert rec_yt["status"] == VideoStatus.UPLOADED

        rec_pin = db.get_video("pin_fail", platform="pinterest")
        assert rec_pin["status"] == VideoStatus.FAILED
        assert "Google Drive 503" in rec_pin["error_message"]
