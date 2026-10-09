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
        """Create tables and indexes if they do not exist, and migrate legacy schema safely."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Check if videos table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='videos'")
            table_exists = cursor.fetchone() is not None

            if not table_exists:
                # Fresh database initialization with multi-platform support
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS videos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform TEXT NOT NULL DEFAULT 'youtube',
                        source_id TEXT NOT NULL,
                        youtube_video_id TEXT,
                        channel_id TEXT,
                        channel_name TEXT,
                        title TEXT NOT NULL,
                        canonical_url TEXT NOT NULL,
                        youtube_url TEXT,
                        search_keyword TEXT,
                        published_at TEXT,
                        duration INTEGER,
                        status TEXT NOT NULL,
                        drive_file_id TEXT,
                        drive_path TEXT,
                        downloaded_at TEXT,
                        uploaded_at TEXT,
                        error_message TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(platform, source_id)
                    )
                    """
                )
            else:
                # Inspect existing columns to check if migration is needed
                cursor.execute("PRAGMA table_info(videos)")
                columns = [row["name"] for row in cursor.fetchall()]

                if "platform" not in columns or "source_id" not in columns:
                    # Migrate existing schema safely while preserving all data
                    cursor.execute(
                        """
                        CREATE TABLE videos_migration (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            platform TEXT NOT NULL DEFAULT 'youtube',
                            source_id TEXT NOT NULL,
                            youtube_video_id TEXT,
                            channel_id TEXT,
                            channel_name TEXT,
                            title TEXT NOT NULL,
                            canonical_url TEXT NOT NULL,
                            youtube_url TEXT,
                            search_keyword TEXT,
                            published_at TEXT,
                            duration INTEGER,
                            status TEXT NOT NULL,
                            drive_file_id TEXT,
                            drive_path TEXT,
                            downloaded_at TEXT,
                            uploaded_at TEXT,
                            error_message TEXT,
                            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(platform, source_id)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO videos_migration (
                            id, platform, source_id, youtube_video_id, channel_id, channel_name,
                            title, canonical_url, youtube_url, search_keyword, published_at,
                            duration, status, drive_file_id, drive_path, downloaded_at,
                            uploaded_at, error_message, created_at, updated_at
                        )
                        SELECT
                            id,
                            'youtube',
                            youtube_video_id,
                            youtube_video_id,
                            channel_id,
                            channel_name,
                            title,
                            youtube_url,
                            youtube_url,
                            NULL,
                            published_at,
                            duration,
                            status,
                            drive_file_id,
                            drive_path,
                            downloaded_at,
                            uploaded_at,
                            error_message,
                            created_at,
                            updated_at
                        FROM videos
                        """
                    )
                    cursor.execute("DROP TABLE videos")
                    cursor.execute("ALTER TABLE videos_migration RENAME TO videos")

            # Indexes for high performance querying
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_platform_source ON videos(platform, source_id)"
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
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_keyword ON videos(search_keyword)"
            )

    def is_video_processed(self, source_id: str, platform: str = "youtube") -> bool:
        """Check if video has already been successfully uploaded or intentionally skipped."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status FROM videos
                WHERE (platform = ? AND source_id = ?) OR youtube_video_id = ?
                LIMIT 1
                """,
                (platform, source_id, source_id),
            )
            row = cursor.fetchone()
            if not row:
                return False
            return row["status"] in (VideoStatus.UPLOADED, VideoStatus.SKIPPED)

    def get_video(self, source_id: str, platform: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve video record by source ID and optional platform."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if platform:
                cursor.execute(
                    "SELECT * FROM videos WHERE platform = ? AND source_id = ? LIMIT 1",
                    (platform, source_id),
                )
            else:
                cursor.execute(
                    "SELECT * FROM videos WHERE source_id = ? OR youtube_video_id = ? LIMIT 1",
                    (source_id, source_id),
                )
            row = cursor.fetchone()
            return dict(row) if row else None

    def upsert_video(
        self,
        source_id: Optional[str] = None,
        title: str = "",
        canonical_url: Optional[str] = None,
        platform: str = "youtube",
        youtube_video_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        channel_name: Optional[str] = None,
        youtube_url: Optional[str] = None,
        search_keyword: Optional[str] = None,
        published_at: Optional[str] = None,
        duration: Optional[int] = None,
        status: str = VideoStatus.DISCOVERED,
        drive_file_id: Optional[str] = None,
        drive_path: Optional[str] = None,
        downloaded_at: Optional[str] = None,
        uploaded_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Insert a newly discovered video or update its metadata if not already completed.

        Preserves multiple discovery keywords when a candidate is discovered by several queries.
        """
        # Maintain backwards compatibility for calls passing youtube_video_id and youtube_url
        effective_source_id = source_id or youtube_video_id or ""
        effective_canonical_url = canonical_url or youtube_url or ""
        effective_yt_id = youtube_video_id or (effective_source_id if platform == "youtube" else None)
        effective_yt_url = youtube_url or (effective_canonical_url if platform == "youtube" else None)

        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO videos (
                    platform, source_id, youtube_video_id, channel_id, channel_name,
                    title, canonical_url, youtube_url, search_keyword, published_at,
                    duration, status, drive_file_id, drive_path, downloaded_at,
                    uploaded_at, error_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, source_id) DO UPDATE SET
                    channel_id = COALESCE(excluded.channel_id, videos.channel_id),
                    channel_name = COALESCE(excluded.channel_name, videos.channel_name),
                    title = excluded.title,
                    canonical_url = excluded.canonical_url,
                    youtube_url = COALESCE(excluded.youtube_url, videos.youtube_url),
                    published_at = COALESCE(excluded.published_at, videos.published_at),
                    duration = COALESCE(excluded.duration, videos.duration),
                    search_keyword = CASE
                        WHEN excluded.search_keyword IS NULL OR excluded.search_keyword = '' THEN videos.search_keyword
                        WHEN videos.search_keyword IS NULL OR videos.search_keyword = '' THEN excluded.search_keyword
                        WHEN instr(videos.search_keyword, excluded.search_keyword) > 0 THEN videos.search_keyword
                        ELSE videos.search_keyword || ', ' || excluded.search_keyword
                    END,
                    updated_at = excluded.updated_at
                WHERE videos.status != 'UPLOADED'
                """,
                (
                    platform,
                    effective_source_id,
                    effective_yt_id,
                    channel_id,
                    channel_name,
                    title,
                    effective_canonical_url,
                    effective_yt_url,
                    search_keyword,
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
        source_id: Optional[str] = None,
        status: str = VideoStatus.DISCOVERED,
        drive_file_id: Optional[str] = None,
        drive_path: Optional[str] = None,
        downloaded_at: Optional[str] = None,
        uploaded_at: Optional[str] = None,
        error_message: Optional[str] = None,
        platform: Optional[str] = None,
        youtube_video_id: Optional[str] = None,
    ) -> None:
        """Update the workflow status and associated metadata for a video."""
        target_id = source_id or youtube_video_id or ""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if platform:
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
                    WHERE platform = ? AND source_id = ?
                    """,
                    (
                        status,
                        drive_file_id,
                        drive_path,
                        downloaded_at,
                        uploaded_at,
                        error_message,
                        now_iso,
                        platform,
                        target_id,
                    ),
                )
            else:
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
                    WHERE source_id = ? OR youtube_video_id = ?
                    """,
                    (
                        status,
                        drive_file_id,
                        drive_path,
                        downloaded_at,
                        uploaded_at,
                        error_message,
                        now_iso,
                        target_id,
                        target_id,
                    ),
                )

    def get_channel_selection_counts(self) -> Dict[str, int]:
        """Get the count of successfully uploaded or active videos per channel/source for fair distribution."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COALESCE(channel_id, channel_name, platform, 'unknown') as ch_key, COUNT(*) as cnt
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
                "SELECT platform, source_id, youtube_video_id FROM videos WHERE status = ?",
                (VideoStatus.DOWNLOADING,),
            )
            downloading_videos = cursor.fetchall()

            for row in downloading_videos:
                plat = row["platform"]
                sid = row["source_id"]
                yid = row["youtube_video_id"]
                check_ids = [s for s in (sid, yid) if s]

                # Clean up any leftover temporary files for this video ID
                matching_temp_files = []
                for cid in check_ids:
                    matching_temp_files.extend(list(temp_dir.glob(f"*{cid}*")))

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
                        WHERE platform = ? AND source_id = ?
                        """,
                        (VideoStatus.DISCOVERED, plat, sid),
                    )
                    recovered_downloading += 1

        return {"reset_from_downloading": recovered_downloading}

    def retry_failed_videos(self, platform: Optional[str] = None) -> int:
        """Reset all FAILED video records back to DISCOVERED to allow retry."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if platform:
                cursor.execute(
                    """
                    UPDATE videos
                    SET status = ?, error_message = NULL, updated_at = ?
                    WHERE status = ? AND platform = ?
                    """,
                    (
                        VideoStatus.DISCOVERED,
                        datetime.now(timezone.utc).isoformat(),
                        VideoStatus.FAILED,
                        platform,
                    ),
                )
            else:
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

            cursor.execute("SELECT platform, COUNT(*) as cnt FROM videos GROUP BY platform")
            platform_counts = {row["platform"]: row["cnt"] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) as total FROM videos")
            total = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT COALESCE(channel_name, search_keyword, platform, 'Unknown') as src_name,
                       platform, COUNT(*) as cnt
                FROM videos
                WHERE status = 'UPLOADED'
                GROUP BY src_name, platform
                ORDER BY cnt DESC
                """
            )
            channel_stats = [
                {
                    "channel": row["src_name"] or "Unknown",
                    "platform": row["platform"],
                    "uploaded": row["cnt"],
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT platform, source_id, youtube_video_id, title, error_message, updated_at
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
                "platform_counts": platform_counts,
                "channel_stats": channel_stats,
                "recent_failures": recent_failures,
            }
