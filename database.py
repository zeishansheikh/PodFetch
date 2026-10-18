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

            # Nature Cinematic Reel Maker Tables
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS nature_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    categories TEXT NOT NULL,
                    custom_keywords TEXT,
                    excluded_terms TEXT,
                    search_limit INTEGER DEFAULT 15,
                    daily_processing_limit INTEGER DEFAULT 10,
                    min_quality_score REAL DEFAULT 65.0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS nature_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT UNIQUE NOT NULL,
                    platform TEXT DEFAULT 'pinterest',
                    title TEXT,
                    canonical_url TEXT,
                    category TEXT NOT NULL,
                    search_keyword TEXT,
                    width INTEGER,
                    height INTEGER,
                    duration_seconds REAL,
                    fps REAL,
                    bitrate INTEGER,
                    thumbnail_url TEXT,
                    creator_attribution TEXT,
                    overall_score REAL DEFAULT 0.0,
                    technical_score REAL DEFAULT 0.0,
                    visual_clarity_score REAL DEFAULT 0.0,
                    vertical_suitability_score REAL DEFAULT 0.0,
                    scenic_relevance_score REAL DEFAULT 0.0,
                    is_eligible INTEGER DEFAULT 1,
                    eligibility_status TEXT DEFAULT 'ELIGIBLE',
                    rejection_reason TEXT,
                    raw_metadata TEXT,
                    published_at TEXT,
                    recency_status TEXT DEFAULT 'unknown',
                    pre_score REAL DEFAULT 0.0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_nature_candidates_category ON nature_candidates(category)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_nature_candidates_eligibility ON nature_candidates(eligibility_status)"
            )

            # Safely add any new columns to existing nature_candidates table
            cursor.execute("PRAGMA table_info(nature_candidates)")
            nc_cols = [row["name"] for row in cursor.fetchall()]
            if "published_at" not in nc_cols:
                cursor.execute("ALTER TABLE nature_candidates ADD COLUMN published_at TEXT")
            if "recency_status" not in nc_cols:
                cursor.execute("ALTER TABLE nature_candidates ADD COLUMN recency_status TEXT DEFAULT 'unknown'")
            if "pre_score" not in nc_cols:
                cursor.execute("ALTER TABLE nature_candidates ADD COLUMN pre_score REAL DEFAULT 0.0")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS nature_keyword_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    query TEXT NOT NULL,
                    mood TEXT DEFAULT 'any',
                    season TEXT DEFAULT 'any',
                    candidates_found INTEGER DEFAULT 0,
                    videos_found INTEGER DEFAULT 0,
                    eligible_found INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_nature_kw_hist_cat ON nature_keyword_history(category)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_nature_kw_hist_created ON nature_keyword_history(created_at)"
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS nature_reels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    candidate_url TEXT,
                    category TEXT NOT NULL,
                    keyword TEXT,
                    original_video_path TEXT,
                    rendered_reel_path TEXT,
                    thumbnail_path TEXT,
                    thought_text TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    hashtags TEXT,
                    title_hook TEXT,
                    creator_attribution TEXT,
                    template_name TEXT DEFAULT 'Nature Cinematic — Thought Reel',
                    template_version TEXT DEFAULT '1.0.0',
                    composition_mode TEXT DEFAULT 'crop',
                    duration_seconds REAL DEFAULT 10.0,
                    width INTEGER DEFAULT 1080,
                    height INTEGER DEFAULT 1920,
                    fps INTEGER DEFAULT 30,
                    ai_model_name TEXT,
                    status TEXT DEFAULT 'PENDING',
                    drive_file_id TEXT,
                    drive_link TEXT,
                    uploaded_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_nature_reels_status ON nature_reels(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_nature_reels_category ON nature_reels(category)"
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS nature_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    stage TEXT DEFAULT 'IDLE',
                    progress INTEGER DEFAULT 0,
                    total_candidates INTEGER DEFAULT 0,
                    processed_candidates INTEGER DEFAULT 0,
                    rendered_reels INTEGER DEFAULT 0,
                    current_category TEXT,
                    current_keyword TEXT,
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_nature_jobs_job_id ON nature_jobs(job_id)"
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

    # ---------------- Nature Cinematic Reel Maker Persistence ----------------

    def save_nature_profile(self, profile_data: Dict[str, Any]) -> None:
        """Insert or update Nature search profile."""
        import json

        categories_json = json.dumps(profile_data.get("categories", []))
        custom_kw_json = json.dumps(profile_data.get("custom_keywords", {}))
        excluded_json = json.dumps(profile_data.get("excluded_terms", []))
        now = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO nature_profiles (
                    name, categories, custom_keywords, excluded_terms,
                    search_limit, daily_processing_limit, min_quality_score,
                    is_active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    categories = excluded.categories,
                    custom_keywords = excluded.custom_keywords,
                    excluded_terms = excluded.excluded_terms,
                    search_limit = excluded.search_limit,
                    daily_processing_limit = excluded.daily_processing_limit,
                    min_quality_score = excluded.min_quality_score,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_data.get("name", "Nature Cinematic Reels"),
                    categories_json,
                    custom_kw_json,
                    excluded_json,
                    int(profile_data.get("search_limit", 15)),
                    int(profile_data.get("daily_processing_limit", 10)),
                    float(profile_data.get("min_quality_score", 65.0)),
                    1 if profile_data.get("is_active", True) else 0,
                    now,
                ),
            )

    def get_nature_profile(self, name: str = "Nature Cinematic Reels") -> Optional[Dict[str, Any]]:
        """Fetch Nature profile by name."""
        import json

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nature_profiles WHERE name = ? LIMIT 1", (name,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                res["categories"] = json.loads(res["categories"])
            except Exception:
                res["categories"] = []
            try:
                res["custom_keywords"] = json.loads(res["custom_keywords"] or "{}")
            except Exception:
                res["custom_keywords"] = {}
            try:
                res["excluded_terms"] = json.loads(res["excluded_terms"] or "[]")
            except Exception:
                res["excluded_terms"] = []
            res["is_active"] = bool(res["is_active"])
            return res

    def save_nature_candidate(self, candidate_data: Dict[str, Any]) -> int:
        """Insert or update a discovered nature video candidate."""
        import json

        now = datetime.now(timezone.utc).isoformat()
        raw_meta = json.dumps(candidate_data.get("raw_metadata", {}))

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO nature_candidates (
                    source_id, platform, title, canonical_url, category,
                    search_keyword, width, height, duration_seconds, fps,
                    bitrate, thumbnail_url, creator_attribution, overall_score,
                    technical_score, visual_clarity_score, vertical_suitability_score,
                    scenic_relevance_score, is_eligible, eligibility_status,
                    rejection_reason, raw_metadata, published_at, recency_status,
                    pre_score, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title = COALESCE(excluded.title, nature_candidates.title),
                    width = COALESCE(excluded.width, nature_candidates.width),
                    height = COALESCE(excluded.height, nature_candidates.height),
                    duration_seconds = COALESCE(excluded.duration_seconds, nature_candidates.duration_seconds),
                    fps = COALESCE(excluded.fps, nature_candidates.fps),
                    bitrate = COALESCE(excluded.bitrate, nature_candidates.bitrate),
                    overall_score = excluded.overall_score,
                    technical_score = excluded.technical_score,
                    visual_clarity_score = excluded.visual_clarity_score,
                    vertical_suitability_score = excluded.vertical_suitability_score,
                    scenic_relevance_score = excluded.scenic_relevance_score,
                    is_eligible = excluded.is_eligible,
                    eligibility_status = excluded.eligibility_status,
                    rejection_reason = excluded.rejection_reason,
                    published_at = COALESCE(excluded.published_at, nature_candidates.published_at),
                    recency_status = COALESCE(excluded.recency_status, nature_candidates.recency_status),
                    pre_score = COALESCE(excluded.pre_score, nature_candidates.pre_score),
                    updated_at = excluded.updated_at
                """,
                (
                    candidate_data.get("source_id"),
                    candidate_data.get("platform", "pinterest"),
                    candidate_data.get("title", ""),
                    candidate_data.get("canonical_url", ""),
                    candidate_data.get("category", "autumn_forest"),
                    candidate_data.get("search_keyword", ""),
                    candidate_data.get("width"),
                    candidate_data.get("height"),
                    candidate_data.get("duration_seconds"),
                    candidate_data.get("fps"),
                    candidate_data.get("bitrate"),
                    candidate_data.get("thumbnail_url"),
                    candidate_data.get("creator_attribution"),
                    candidate_data.get("overall_score", 0.0),
                    candidate_data.get("technical_score", 0.0),
                    candidate_data.get("visual_clarity_score", 0.0),
                    candidate_data.get("vertical_suitability_score", 0.0),
                    candidate_data.get("scenic_relevance_score", 0.0),
                    1 if candidate_data.get("is_eligible", True) else 0,
                    candidate_data.get("eligibility_status", "ELIGIBLE"),
                    candidate_data.get("rejection_reason"),
                    raw_meta,
                    candidate_data.get("published_at"),
                    candidate_data.get("recency_status", "unknown"),
                    candidate_data.get("pre_score", 0.0),
                    now,
                ),
            )
            return cursor.lastrowid

    def get_nature_candidates(self, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent nature candidates, optionally filtered by category."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute(
                    "SELECT * FROM nature_candidates WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                    (category, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM nature_candidates ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            return [dict(r) for r in cursor.fetchall()]

    def record_nature_keyword_search(
        self,
        category: str,
        keyword: str,
        query: str,
        mood: str = "any",
        season: str = "any",
        candidates_found: int = 0,
        videos_found: int = 0,
        eligible_found: int = 0,
    ) -> int:
        """Record a keyword discovery execution and its yield in nature_keyword_history."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO nature_keyword_history (
                    category, keyword, query, mood, season,
                    candidates_found, videos_found, eligible_found
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category,
                    keyword,
                    query,
                    mood,
                    season,
                    candidates_found,
                    videos_found,
                    eligible_found,
                ),
            )
            return cursor.lastrowid

    def get_nature_keyword_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch recent keyword searches and their candidate yield."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM nature_keyword_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_all_nature_candidate_ids(self) -> set:
        """Fetch all previously discovered or processed nature candidate source IDs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT source_id FROM nature_candidates")
            cands = {row["source_id"] for row in cursor.fetchall()}
            cursor.execute("SELECT source_id FROM nature_reels")
            reels = {row["source_id"] for row in cursor.fetchall()}
            return cands.union(reels)

    def save_nature_reel(self, reel_data: Dict[str, Any]) -> int:
        """Insert a newly rendered nature reel."""
        import json

        tags_val = reel_data.get("hashtags", [])
        tags_str = json.dumps(tags_val) if isinstance(tags_val, list) else str(tags_val)
        now = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO nature_reels (
                    source_id, candidate_url, category, keyword,
                    original_video_path, rendered_reel_path, thumbnail_path,
                    thought_text, caption, hashtags, title_hook,
                    creator_attribution, template_name, template_version,
                    composition_mode, duration_seconds, width, height, fps,
                    ai_model_name, status, drive_file_id, drive_link,
                    uploaded_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reel_data.get("source_id", ""),
                    reel_data.get("candidate_url", ""),
                    reel_data.get("category", "mountains"),
                    reel_data.get("keyword", ""),
                    reel_data.get("original_video_path", ""),
                    reel_data.get("rendered_reel_path", ""),
                    reel_data.get("thumbnail_path"),
                    reel_data.get("thought_text", ""),
                    reel_data.get("caption", ""),
                    tags_str,
                    reel_data.get("title_hook"),
                    reel_data.get("creator_attribution"),
                    reel_data.get("template_name", "Nature Cinematic — Thought Reel"),
                    reel_data.get("template_version", "1.0.0"),
                    reel_data.get("composition_mode", "crop"),
                    float(reel_data.get("duration_seconds", 10.0)),
                    int(reel_data.get("width", 1080)),
                    int(reel_data.get("height", 1920)),
                    int(reel_data.get("fps", 30)),
                    reel_data.get("ai_model_name", "openai/gpt-oss-20b"),
                    reel_data.get("status", "PENDING"),
                    reel_data.get("drive_file_id"),
                    reel_data.get("drive_link"),
                    reel_data.get("uploaded_at"),
                    now,
                    now,
                ),
            )
            return cursor.lastrowid

    def get_nature_reels(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent nature reels with parsed hashtags."""
        import json

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM nature_reels WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM nature_reels ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = [dict(r) for r in cursor.fetchall()]
            for r in rows:
                if r.get("hashtags"):
                    try:
                        r["hashtags"] = json.loads(r["hashtags"])
                    except Exception:
                        r["hashtags"] = [t.strip() for t in str(r["hashtags"]).split(",") if t.strip()]
                else:
                    r["hashtags"] = []
            return rows

    def get_nature_reel_by_id(self, reel_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single nature reel by primary key ID."""
        import json

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nature_reels WHERE id = ? LIMIT 1", (reel_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("hashtags"):
                try:
                    res["hashtags"] = json.loads(res["hashtags"])
                except Exception:
                    res["hashtags"] = [t.strip() for t in str(res["hashtags"]).split(",") if t.strip()]
            else:
                res["hashtags"] = []
            return res

    def update_nature_reel_status(self, reel_id: int, status: str) -> bool:
        """Update approval status (PENDING, APPROVED, REJECTED)."""
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE nature_reels SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, reel_id),
            )
            return cursor.rowcount > 0

    def update_nature_reel_draft(
        self, reel_id: int, thought_text: str, caption: str, hashtags: List[str]
    ) -> bool:
        """Update editable thought text, caption, and hashtags before approval."""
        import json

        tags_str = json.dumps(hashtags)
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE nature_reels
                SET thought_text = ?, caption = ?, hashtags = ?, updated_at = ?
                WHERE id = ?
                """,
                (thought_text, caption, tags_str, now, reel_id),
            )
            return cursor.rowcount > 0

    def update_nature_reel_drive(self, reel_id: int, file_id: str, web_link: str) -> bool:
        """Record Google Drive upload completion on nature reel."""
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE nature_reels
                SET drive_file_id = ?, drive_link = ?, uploaded_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (file_id, web_link, now, now, reel_id),
            )
            return cursor.rowcount > 0

    def get_recent_nature_thoughts(self, limit: int = 50) -> List[str]:
        """Fetch recent thoughts to prevent repetitive text generation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT thought_text FROM nature_reels ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            return [row["thought_text"] for row in cursor.fetchall() if row["thought_text"]]

    def save_nature_job(self, job_data: Dict[str, Any]) -> None:
        """Record or update active pipeline job execution status."""
        now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO nature_jobs (
                    job_id, stage, progress, total_candidates,
                    processed_candidates, rendered_reels, current_category,
                    current_keyword, error_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    stage = excluded.stage,
                    progress = excluded.progress,
                    total_candidates = excluded.total_candidates,
                    processed_candidates = excluded.processed_candidates,
                    rendered_reels = excluded.rendered_reels,
                    current_category = excluded.current_category,
                    current_keyword = excluded.current_keyword,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    job_data.get("job_id"),
                    job_data.get("stage", "IDLE"),
                    int(job_data.get("progress", 0)),
                    int(job_data.get("total_candidates", 0)),
                    int(job_data.get("processed_candidates", 0)),
                    int(job_data.get("rendered_reels", 0)),
                    job_data.get("current_category"),
                    job_data.get("current_keyword"),
                    job_data.get("error_message"),
                    now,
                ),
            )

    def get_latest_nature_job(self) -> Optional[Dict[str, Any]]:
        """Retrieve most recent pipeline execution state."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nature_jobs ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

