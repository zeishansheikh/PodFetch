"""
Unit tests for SQLite database operations, duplicate detection, and crash recovery.
"""

import sqlite3
from pathlib import Path
import pytest

from database import Database, VideoStatus


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_downloads.db"
    return Database(db_file)


def test_db_initialization_and_schema(temp_db: Database):
    with temp_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='videos'")
        assert cursor.fetchone() is not None


def test_unique_constraint_on_video_id(temp_db: Database):
    temp_db.upsert_video(
        youtube_video_id="vid_001",
        title="Podcast Ep 1",
        youtube_url="https://youtube.com/watch?v=vid_001",
    )
    # Upserting again should update instead of throwing an unhandled duplicate error
    temp_db.upsert_video(
        youtube_video_id="vid_001",
        title="Podcast Ep 1 Updated",
        youtube_url="https://youtube.com/watch?v=vid_001",
    )
    video = temp_db.get_video("vid_001")
    assert video is not None
    assert video["title"] == "Podcast Ep 1 Updated"


def test_duplicate_detection(temp_db: Database):
    assert not temp_db.is_video_processed("vid_002")

    temp_db.upsert_video(
        youtube_video_id="vid_002",
        title="Podcast Ep 2",
        youtube_url="https://youtube.com/watch?v=vid_002",
        status=VideoStatus.DISCOVERED,
    )
    assert not temp_db.is_video_processed("vid_002")

    temp_db.update_status("vid_002", status=VideoStatus.UPLOADED, drive_file_id="drive_123")
    assert temp_db.is_video_processed("vid_002")


def test_crash_recovery_resets_stuck_downloading(temp_db: Database, tmp_path: Path):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    # Video stuck in DOWNLOADING with no file
    temp_db.upsert_video(
        youtube_video_id="vid_stuck",
        title="Stuck Video",
        youtube_url="https://youtube.com/watch?v=vid_stuck",
        status=VideoStatus.DOWNLOADING,
    )

    res = temp_db.recover_interrupted_states(temp_dir)
    assert res["reset_from_downloading"] == 1

    vid_record = temp_db.get_video("vid_stuck")
    assert vid_record["status"] == VideoStatus.DISCOVERED


def test_retry_failed_videos(temp_db: Database):
    temp_db.upsert_video(
        youtube_video_id="vid_fail",
        title="Failed Video",
        youtube_url="https://youtube.com/watch?v=vid_fail",
        status=VideoStatus.FAILED,
        error_message="Network timeout",
    )
    reset_count = temp_db.retry_failed_videos()
    assert reset_count == 1

    vid = temp_db.get_video("vid_fail")
    assert vid["status"] == VideoStatus.DISCOVERED
    assert vid["error_message"] is None


def test_channel_selection_counts(temp_db: Database):
    temp_db.upsert_video(
        youtube_video_id="v1",
        title="Ep 1",
        youtube_url="https://y.com/1",
        channel_id="ch_A",
        status=VideoStatus.UPLOADED,
    )
    temp_db.upsert_video(
        youtube_video_id="v2",
        title="Ep 2",
        youtube_url="https://y.com/2",
        channel_id="ch_A",
        status=VideoStatus.UPLOADED,
    )
    temp_db.upsert_video(
        youtube_video_id="v3",
        title="Ep 3",
        youtube_url="https://y.com/3",
        channel_id="ch_B",
        status=VideoStatus.UPLOADED,
    )

    counts = temp_db.get_channel_selection_counts()
    assert counts.get("ch_A") == 2
    assert counts.get("ch_B") == 1
