"""
Integration test verifying error isolation:
When Video A succeeds, Video B fails, and Video C succeeds,
processing must continue, and the database must record the failure reason.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from config import AppConfig
from database import Database, VideoStatus
from filters import VideoCandidate
from main import execute_pipeline


@pytest.fixture
def test_env(tmp_path: Path):
    db_path = tmp_path / "isolation_test.db"
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    config = AppConfig(
        youtube_channels=["https://www.youtube.com/@testchannel"],
        min_videos_per_run=3,
        max_videos_per_run=3,
        google_drive_folder_id="drive_mock_folder",
        database_path=db_path,
        temp_dir=temp_dir,
        log_dir=log_dir,
        dry_run=False,
    )
    db = Database(db_path)
    return config, db, temp_dir


def test_pipeline_error_isolation(test_env, monkeypatch):
    config, db, temp_dir = test_env

    # Setup 3 video candidates
    candidates = [
        VideoCandidate("vid_A", "ch1", "Test Channel", "Episode A", "https://yt.com/A", duration_seconds=3600),
        VideoCandidate("vid_B", "ch1", "Test Channel", "Episode B", "https://yt.com/B", duration_seconds=3600),
        VideoCandidate("vid_C", "ch1", "Test Channel", "Episode C", "https://yt.com/C", duration_seconds=3600),
    ]

    # Mock ChannelDiscoverer to return our 3 candidates
    with patch("main.ChannelDiscoverer") as mock_disc_cls:
        mock_disc = MagicMock()
        mock_disc.collect_and_filter_all_channels.return_value = (
            {"ch1": candidates},
            3,
            0,
        )
        mock_disc_cls.return_value = mock_disc

        # Mock VideoDownloader
        with patch("main.VideoDownloader") as mock_dl_cls:
            mock_dl = MagicMock()

            def fake_download(cand: VideoCandidate):
                if cand.youtube_video_id == "vid_B":
                    raise RuntimeError("Simulated network failure on video B")
                fake_file = temp_dir / f"{cand.youtube_video_id}.mp4"
                fake_file.write_bytes(b"dummy video data")
                return fake_file

            mock_dl.download_video.side_effect = fake_download
            mock_dl_cls.return_value = mock_dl

            # Mock GoogleDriveUploader
            with patch("main.GoogleDriveUploader") as mock_uploader_cls:
                mock_uploader = MagicMock()
                mock_uploader.upload_video.return_value = ("mock_drive_file_id_xyz", "drive/path/file.mp4")
                mock_uploader_cls.return_value = mock_uploader

                # Execute pipeline with exact limit of 3
                exit_code = execute_pipeline(config, cli_limit=3)

                # Since 1 video failed, exit_code is 1, but A and C must be uploaded!
                assert exit_code == 1

                # Verify database states
                rec_a = db.get_video("vid_A")
                assert rec_a is not None
                assert rec_a["status"] == VideoStatus.UPLOADED
                assert rec_a["drive_file_id"] == "mock_drive_file_id_xyz"

                rec_b = db.get_video("vid_B")
                assert rec_b is not None
                assert rec_b["status"] == VideoStatus.FAILED
                assert "Simulated network failure on video B" in rec_b["error_message"]

                rec_c = db.get_video("vid_C")
                assert rec_c is not None
                assert rec_c["status"] == VideoStatus.UPLOADED
                assert rec_c["drive_file_id"] == "mock_drive_file_id_xyz"
