"""
Persistent SQLite database layer for duplicate detection, state management,
and crash-recovery across unattended runs.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


class VideoStatus:
    DISCOVERED = "DISCOVERED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Database:
    """Thread-safe SQLite database manager for video state tracking."""

    def __init__(self, db_path: str | Path = "downloads.db") -> None:
        self.db_path = Path(db_path)
        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a transactional database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_video_id TEXT NOT NULL UNIQUE,
                    channel_id TEXT,
                    channel_name TEXT,
                    title TEXT NOT NULL,
                    youtube_url TEXT NOT NULL,
                    published_at TEXT,
                    duration INTEGER,
                    status TEXT NOT NULL,
                    drive_file_id TEXT,
                    drive_path TEXT,
                    downloaded_at TEXT,
                    uploaded_at TEXT,
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_video_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id)"
            )

    def is_video_processed(self, youtube_video_id: str) -> bool:
        """Check if video has already been successfully uploaded or intentionally skipped."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status FROM videos
                WHERE youtube_video_id = ?
                """,
                (youtube_video_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            return row["status"] in (VideoStatus.UPLOADED, VideoStatus.SKIPPED)

    def get_video(self, youtube_video_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve video record by YouTube video ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM videos WHERE youtube_video_id = ?",
                (youtube_video_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def upsert_video(
        self,
        youtube_video_id: str,
        title: str,
        youtube_url: str,
        channel_id: Optional[str] = None,
        channel_name: Optional[str] = None,
        published_at: Optional[str] = None,
        duration: Optional[int] = None,
        status: str = VideoStatus.DISCOVERED,
        drive_file_id: Optional[str] = None,
        drive_path: Optional[str] = None,
        downloaded_at: Optional[str] = None,
        uploaded_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Insert a newly discovered video or update its metadata if not already completed."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO videos (
                    youtube_video_id, channel_id, channel_name, title, youtube_url,
                    published_at, duration, status, drive_file_id, drive_path,
                    downloaded_at, uploaded_at, error_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(youtube_video_id) DO UPDATE SET
                    channel_id = COALESCE(excluded.channel_id, videos.channel_id),
                    channel_name = COALESCE(excluded.channel_name, videos.channel_name),
                    title = excluded.title,
                    youtube_url = excluded.youtube_url,
                    published_at = COALESCE(excluded.published_at, videos.published_at),
                    duration = COALESCE(excluded.duration, videos.duration),
                    updated_at = excluded.updated_at
                WHERE videos.status != 'UPLOADED'
                """,
                (
                    youtube_video_id,
                    channel_id,
                    channel_name,
                    title,
                    youtube_url,
                    published_at,
                    duration,
                    status,
                    drive_file_id,
                    drive_path,
                    downloaded_at,
                    uploaded_at,
                    error_message,
                    now_iso,
                ),
            )

    def update_status(
        self,
        youtube_video_id: str,
        status: str,
        drive_file_id: Optional[str] = None,
        drive_path: Optional[str] = None,
        downloaded_at: Optional[str] = None,
        uploaded_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update the workflow status and associated metadata for a video."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE videos
                SET status = ?,
                    drive_file_id = COALESCE(?, drive_file_id),
                    drive_path = COALESCE(?, drive_path),
                    downloaded_at = COALESCE(?, downloaded_at),
                    uploaded_at = COALESCE(?, uploaded_at),
                    error_message = ?,
                    updated_at = ?
                WHERE youtube_video_id = ?
                """,
                (
                    status,
                    drive_file_id,
                    drive_path,
                    downloaded_at,
                    uploaded_at,
                    error_message,
                    now_iso,
                    youtube_video_id,
                ),
            )

    def get_channel_selection_counts(self) -> Dict[str, int]:
        """Get the count of successfully uploaded or active videos per channel for fair distribution."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COALESCE(channel_id, channel_name, 'unknown') as ch_key, COUNT(*) as cnt
                FROM videos
                WHERE status IN ('UPLOADED', 'DOWNLOADED', 'DOWNLOADING')
                GROUP BY ch_key
                """
            )
            return {row["ch_key"]: row["cnt"] for row in cursor.fetchall()}

    def recover_interrupted_states(self, temp_dir: Path) -> Dict[str, int]:
        """
        Safe crash recovery:
        - If a video is DOWNLOADING but temp file is missing, reset to DISCOVERED.
        - If a video is DOWNLOADING and an unfinished .part file exists, remove it and reset to DISCOVERED.
        - If a video is DOWNLOADED and the completed local file still exists, keep it as DOWNLOADED so it can upload!
        """
        recovered_downloading = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT youtube_video_id FROM videos WHERE status = ?",
                (VideoStatus.DOWNLOADING,),
            )
            downloading_videos = [row["youtube_video_id"] for row in cursor.fetchall()]

            for vid in downloading_videos:
                # Clean up any leftover temporary files for this video ID
                matching_temp_files = list(temp_dir.glob(f"*{vid}*"))
                has_completed_file = any(
                    f.is_file() and not f.name.endswith(".part") and not f.name.endswith(".ytdl")
                    for f in matching_temp_files
                )

                if not has_completed_file:
                    # Clean up partial files
                    for p in matching_temp_files:
                        try:
                            p.unlink(missing_ok=True)
                        except OSError:
                            pass
                    # Reset to DISCOVERED so next run can process it cleanly
                    cursor.execute(
                        """
                        UPDATE videos
                        SET status = ?, error_message = 'Reset after interrupted download'
                        WHERE youtube_video_id = ?
                        """,
                        (VideoStatus.DISCOVERED, vid),
                    )
                    recovered_downloading += 1

        return {"reset_from_downloading": recovered_downloading}

    def retry_failed_videos(self) -> int:
        """Reset all FAILED video records back to DISCOVERED to allow retry."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE videos
                SET status = ?, error_message = NULL, updated_at = ?
                WHERE status = ?
                """,
                (
                    VideoStatus.DISCOVERED,
                    datetime.now(timezone.utc).isoformat(),
                    VideoStatus.FAILED,
                ),
            )
            return cursor.rowcount

    def get_statistics(self) -> Dict[str, Any]:
        """Generate summary statistics for CLI status display."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) as cnt FROM videos GROUP BY status")
            status_counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) as total FROM videos")
            total = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT channel_name, COUNT(*) as cnt
                FROM videos
                WHERE status = 'UPLOADED'
                GROUP BY channel_name
                ORDER BY cnt DESC
                """
            )
            channel_stats = [
                {"channel": row["channel_name"] or "Unknown", "uploaded": row["cnt"]}
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT youtube_video_id, title, error_message, updated_at
                FROM videos
                WHERE status = 'FAILED'
                ORDER BY updated_at DESC
                LIMIT 5
                """
            )
            recent_failures = [dict(r) for r in cursor.fetchall()]

            return {
                "total_records": total,
                "status_counts": status_counts,
                "channel_stats": channel_stats,
                "recent_failures": recent_failures,
            }
