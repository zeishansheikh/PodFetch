"""
REST API server for PodFetch.
Exposes clean endpoints for the frontend dashboard to discover, download,
track jobs, inspect the media library, and view Drive/system status.
Reuses existing PodFetch backend modules directly without modifying existing CLI behavior.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yt_dlp
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from audio_manifest import AudioManifestManager
from filename_utils import generate_source_filename, sanitize_filename
from config import AppConfig, load_config
from database import Database, VideoStatus
from discovery import ChannelDiscoverer, select_multisource_candidates
from downloader import VideoDownloader
from drive_uploader import GoogleDriveUploader
from filters import VideoCandidate, VideoFilter, is_rap_track, is_sad_song
from instagram_discovery import InstagramAudioDiscoverer, InstagramVideoDiscoverer
from instagram_downloader import InstagramAudioDownloader
from logger import get_logger
from main import execute_pipeline
from pinterest_discovery import PinterestDiscoverer
from pinterest_downloader import PinterestDownloader

logger = get_logger("api")

app = FastAPI(
    title="PodFetch API",
    description="Backend API powering the PodFetch Media Dashboard",
    version="2.0.0",
)

# Enable CORS for local dev servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory background jobs registry
_active_jobs: Dict[str, Dict[str, Any]] = {}


def get_config() -> AppConfig:
    """Load fresh configuration from environment."""
    return load_config()


def get_db(cfg: Optional[AppConfig] = None) -> Database:
    """Get Database instance."""
    config = cfg or get_config()
    return Database(config.database_path)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RunPipelineRequest(BaseModel):
    source: str = Field(default="all", description="Source to run: 'youtube', 'pinterest', 'instagram', or 'all'")
    limit: Optional[int] = Field(default=1, ge=1, le=10, description="Max videos/audios to process")
    channel: Optional[str] = Field(default=None, description="Optional single YouTube channel override")
    dry_run: bool = Field(default=False, description="Whether to simulate run without downloading/uploading")


class DirectDownloadRequest(BaseModel):
    platform: str
    source_id: str
    title: str
    canonical_url: str
    audio_url: Optional[str] = None
    artist: Optional[str] = None
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
    channel_name: Optional[str] = None
    search_keyword: Optional[str] = None
    media_type: str = "video"


class VideoDownloadPayload(BaseModel):
    url: str
    platform: Optional[str] = "youtube"
    title: Optional[str] = None
    upload_to_drive: bool = True


class InstagramAudioPayload(BaseModel):
    audio_asset_id: str
    audio_url: Optional[str] = None
    title: str = "Untitled Audio"
    artist: Optional[str] = None
    upload_to_drive: bool = True


class YouTubeDiscoverPayload(BaseModel):
    channels: Optional[List[str]] = None
    channel: Optional[str] = None
    max_videos: int = 10


class PinterestDiscoverPayload(BaseModel):
    keyword: Optional[str] = None
    max_videos: int = 15


class InstagramDiscoverPayload(BaseModel):
    query: Optional[str] = None
    target: Optional[str] = None
    media_filter: Optional[str] = "video"
    audio_type: Optional[str] = "music"
    limit: int = 15
    sad_preference: bool = True
    avoid_rap: bool = True


class RetryFailedRequest(BaseModel):
    platform: Optional[str] = None


# ---------------------------------------------------------------------------
# Health & Statistics
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "app": "PodFetch",
        "name": "PodFetch API",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/stats")
def get_dashboard_stats() -> Dict[str, Any]:
    """Return live system statistics from SQLite database and manifest."""
    config = get_config()
    db = get_db(config)
    stats = db.get_statistics()
    status_counts = stats.get("status_counts", {})
    platform_counts = stats.get("platform_counts", {})
    total_recs = stats.get("total_records", 0)

    # Audio manifest count
    manifest_mgr = AudioManifestManager(config.instagram_audio_manifest_path)
    audio_count = len(manifest_mgr.load_manifest().get("tracks", []))

    # Active running jobs count
    running_jobs = sum(1 for j in _active_jobs.values() if j.get("status") == "RUNNING")

    return {
        "total_records": total_recs,
        "total_processed": total_recs,
        "uploaded": status_counts.get("UPLOADED", 0),
        "completed": status_counts.get("COMPLETED", 0),
        "discovered": status_counts.get("DISCOVERED", 0),
        "failed": status_counts.get("FAILED", 0),
        "skipped": status_counts.get("SKIPPED", 0),
        "status_counts": status_counts,
        "platform_counts": platform_counts,
        "by_platform": platform_counts,
        "channel_stats": stats.get("channel_stats", []),
        "recent_failures": stats.get("recent_failures", []),
        "instagram_manifest_tracks": audio_count,
        "running_jobs_count": running_jobs,
        "enabled_sources": config.enabled_sources,
        "drive_configured": bool(config.google_drive_folder_id),
        "google_drive_configured": bool(config.google_drive_folder_id),
        "instagram_configured": bool(config.instagram_account_id and config.instagram_access_token),
        "total_size_bytes": 0,
    }


# ---------------------------------------------------------------------------
# Media Library
# ---------------------------------------------------------------------------


@app.get("/api/library")
def get_library_records(
    platform: Optional[str] = Query(None, description="Filter by platform: youtube, pinterest, instagram"),
    status: Optional[str] = Query(None, description="Filter by status: UPLOADED, FAILED, DISCOVERED, etc."),
    search: Optional[str] = Query(None, description="Search term in title, channel_name, or keyword"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Fetch paginated media records from downloads.db with optional filtering."""
    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()

        query_conditions: List[str] = []
        params: List[Any] = []

        if platform and platform.lower() != "all":
            norm_plat = "instagram" if "instagram" in platform.lower() else platform.lower()
            query_conditions.append("platform = ?")
            params.append(norm_plat)

        if status and status.upper() != "ALL":
            query_conditions.append("status = ?")
            params.append(status.upper())

        if search and isinstance(search, str) and search.strip():
            term = f"%{search.strip()}%"
            query_conditions.append(
                "(title LIKE ? OR channel_name LIKE ? OR search_keyword LIKE ? OR source_id LIKE ?)"
            )
            params.extend([term, term, term, term])

        where_clause = ""
        if query_conditions:
            where_clause = "WHERE " + " AND ".join(query_conditions)

        # Count total matches
        count_sql = f"SELECT COUNT(*) as total FROM videos {where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()["total"]

        # Fetch records
        select_sql = f"""
            SELECT id, platform, source_id, youtube_video_id, channel_id, channel_name,
                   title, canonical_url, youtube_url, search_keyword, published_at,
                   duration, status, drive_file_id, drive_path, downloaded_at,
                   uploaded_at, error_message, created_at, updated_at
            FROM videos
            {where_clause}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        fetch_params = params + [limit, offset]
        cursor.execute(select_sql, fetch_params)
        rows = [dict(row) for row in cursor.fetchall()]

        # Enhance items with mood / tags where applicable
        for r in rows:
            if r.get("platform") == "instagram":
                r["is_sad"] = is_sad_song(r.get("title"), r.get("channel_name"))
                is_rap, rap_msg = is_rap_track(r.get("title"), r.get("channel_name"))
                r["is_rap"] = is_rap

        return {
            "total": total,
            "items": rows,
            "limit": limit,
            "offset": offset,
        }


# ---------------------------------------------------------------------------
# Processing Queue
# ---------------------------------------------------------------------------


@app.get("/api/queue")
def get_queue_items() -> Dict[str, Any]:
    """Retrieve items currently in queue or processing, along with active API background jobs."""
    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, platform, source_id, youtube_video_id, channel_name,
                   title, canonical_url, duration, status, error_message,
                   created_at, updated_at
            FROM videos
            WHERE status IN ('DOWNLOADING', 'DOWNLOADED', 'DISCOVERED', 'FAILED')
            ORDER BY 
                CASE status
                    WHEN 'DOWNLOADING' THEN 1
                    WHEN 'DOWNLOADED' THEN 2
                    WHEN 'DISCOVERED' THEN 3
                    WHEN 'FAILED' THEN 4
                    ELSE 5
                END,
                updated_at DESC
            LIMIT 50
            """
        )
        queue_items = [dict(r) for r in cursor.fetchall()]

    # Format active background worker jobs
    jobs_list = sorted(_active_jobs.values(), key=lambda j: j["started_at"], reverse=True)

    return {
        "active_jobs": jobs_list[:10],
        "queue_items": queue_items,
        "counts": {
            "downloading": sum(1 for i in queue_items if i["status"] == "DOWNLOADING"),
            "discovered": sum(1 for i in queue_items if i["status"] == "DISCOVERED"),
            "failed": sum(1 for i in queue_items if i["status"] == "FAILED"),
        },
    }


@app.post("/api/queue/retry-failed")
def retry_failed_jobs(req: RetryFailedRequest) -> Dict[str, Any]:
    """Reset failed items back to DISCOVERED status for re-processing."""
    db = get_db()
    reset_count = db.retry_failed_videos(platform=req.platform)
    return {
        "success": True,
        "reset_count": reset_count,
        "message": f"Successfully reset {reset_count} failed record(s) to DISCOVERED.",
    }


# ---------------------------------------------------------------------------
# Discovery Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/discover/youtube")
def discover_youtube(
    channel: Optional[str] = Query(None, description="YouTube channel URL, handle, ID, video link, or search query"),
    limit: int = Query(10, ge=1, le=30),
) -> Dict[str, Any]:
    """Discover videos from YouTube: supports channels, direct video links, and search queries."""
    config = get_config()
    db = get_db(config)
    target_channel = (channel or "").strip() or (config.youtube_channels[0] if config.youtube_channels else "@hubermanlab")

    # 1. Direct YouTube video URL check
    is_direct_video = any(pat in target_channel for pat in ("/watch?v=", "youtu.be/", "/shorts/", "watch?v="))
    if is_direct_video:
        try:
            ydl_opts = {"extract_flat": True, "quiet": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_channel, download=False)
                vid_id = info.get("id") or "video"
                title = info.get("title") or "YouTube Video"
                uploader = info.get("uploader") or info.get("channel") or "YouTube"
                dur = info.get("duration")
                thumb = info.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
                is_processed = db.is_video_processed(vid_id, platform="youtube")
                items = [{
                    "source_id": vid_id,
                    "video_id": vid_id,
                    "id": vid_id,
                    "title": title,
                    "channel_name": uploader,
                    "channel_id": info.get("channel_id") or "youtube",
                    "url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                    "canonical_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                    "duration_seconds": dur,
                    "duration": dur,
                    "is_processed": is_processed,
                    "platform": "youtube",
                    "thumbnail_url": thumb,
                }]
                return {
                    "source": "youtube",
                    "channel": target_channel,
                    "total_found": 1,
                    "items": items,
                }
        except Exception as e:
            logger.error(f"Direct YouTube probe failed: {e}", exc_info=True)
            return {
                "source": "youtube",
                "channel": target_channel,
                "total_found": 0,
                "items": [],
                "error": str(e),
            }

    # 2. General search query (not a channel handle, channel ID, or URL)
    is_channel = (
        target_channel.startswith("@")
        or target_channel.startswith("UC")
        or "youtube.com/c" in target_channel
        or "youtube.com/user" in target_channel
        or "youtube.com/channel" in target_channel
        or "youtube.com/@" in target_channel
    )

    if not is_channel and not target_channel.startswith("http"):
        try:
            ydl_opts = {"extract_flat": True, "quiet": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(f"ytsearch{limit}:{target_channel}", download=False)
                entries = res.get("entries", [])
                items = []
                for entry in entries:
                    vid_id = entry.get("id") or "video"
                    dur = entry.get("duration")
                    is_processed = db.is_video_processed(vid_id, platform="youtube")
                    items.append({
                        "source_id": vid_id,
                        "video_id": vid_id,
                        "id": vid_id,
                        "title": entry.get("title") or f"YouTube Video {vid_id}",
                        "channel_name": entry.get("uploader") or entry.get("channel") or "YouTube",
                        "channel_id": entry.get("channel_id") or "youtube",
                        "url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                        "canonical_url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                        "duration_seconds": dur,
                        "duration": dur,
                        "is_processed": is_processed,
                        "platform": "youtube",
                        "thumbnail_url": entry.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                    })
                return {
                    "source": "youtube",
                    "channel": target_channel,
                    "total_found": len(items),
                    "items": items,
                }
        except Exception as e:
            logger.error(f"YouTube search probe failed: {e}", exc_info=True)
            return {
                "source": "youtube",
                "channel": target_channel,
                "total_found": 0,
                "items": [],
                "error": str(e),
            }

    # 3. Channel probe
    discoverer = ChannelDiscoverer(config, db)
    try:
        candidates = discoverer.discover_channel_videos(target_channel, max_probe=limit)
        items: List[Dict[str, Any]] = []
        for c in candidates:
            is_processed = db.is_video_processed(c.source_id, platform="youtube")
            items.append({
                "source_id": c.source_id,
                "video_id": c.source_id,
                "id": c.source_id,
                "title": c.title,
                "channel_name": c.channel_name,
                "channel_id": c.channel_id,
                "url": c.canonical_url,
                "canonical_url": c.canonical_url,
                "duration_seconds": c.duration_seconds,
                "duration": c.duration_seconds,
                "is_processed": is_processed,
                "platform": "youtube",
                "thumbnail_url": c.thumbnail_url or f"https://i.ytimg.com/vi/{c.source_id}/hqdefault.jpg",
            })
        return {
            "source": "youtube",
            "channel": target_channel,
            "total_found": len(items),
            "items": items,
        }
    except Exception as e:
        logger.error(f"YouTube discovery failed: {e}", exc_info=True)
        return {
            "source": "youtube",
            "channel": target_channel,
            "total_found": 0,
            "items": [],
            "error": str(e),
        }


@app.get("/api/discover/pinterest")
def discover_pinterest(
    keyword: Optional[str] = Query(None, description="Keyword or Pin URL to search on Pinterest"),
    limit: int = Query(15, ge=1, le=30),
) -> Dict[str, Any]:
    """Discover video Pins from Pinterest matching keyword or Pin URL."""
    config = get_config()
    db = get_db(config)
    search_keyword = (keyword or "").strip() or (config.pinterest_keywords[0] if config.pinterest_keywords else "nature aesthetics")

    discoverer = PinterestDiscoverer(config, db)
    try:
        # Check direct Pin URL
        pin_match = re.search(r"/pin/(\d+)", search_keyword)
        if pin_match:
            pin_id = pin_match.group(1)
            pin_details = discoverer.fetch_pin_details(pin_id)
            if pin_details:
                pins = [pin_details]
            else:
                pins = [discoverer.search_keyword(pin_id)]
        else:
            pins = discoverer.search_keyword(search_keyword)

        items: List[Dict[str, Any]] = []
        for p in pins[:limit]:
            if isinstance(p, list):
                sub_list = p
            else:
                sub_list = [p]
            for pin in sub_list:
                is_processed = db.is_video_processed(pin.pin_id, platform="pinterest")
                items.append({
                    "source_id": pin.pin_id,
                    "pin_id": pin.pin_id,
                    "id": pin.pin_id,
                    "title": pin.title or f"Pin {pin.pin_id}",
                    "description": pin.description,
                    "url": pin.canonical_url,
                    "canonical_url": pin.canonical_url,
                    "thumbnail_url": pin.thumbnail_url,
                    "is_video": pin.is_video,
                    "duration_seconds": pin.duration_seconds,
                    "duration": pin.duration_seconds,
                    "width": pin.width,
                    "height": pin.height,
                    "is_vertical": pin.is_vertical,
                    "is_processed": is_processed,
                    "platform": "pinterest",
                    "keyword": search_keyword,
                })

        return {
            "source": "pinterest",
            "keyword": search_keyword,
            "total_found": len(items),
            "items": items,
        }
    except Exception as e:
        logger.error(f"Pinterest discovery failed: {e}", exc_info=True)
        return {
            "source": "pinterest",
            "keyword": search_keyword,
            "total_found": 0,
            "items": [],
            "error": str(e),
        }


@app.get("/api/discover/instagram")
def discover_instagram(
    query: Optional[str] = Query(None, description="Instagram reel URL, username, handle, hashtag, or keyword"),
    target: Optional[str] = Query(None, description="Alias for query"),
    audio_type: Optional[str] = Query(None, description="'music' or 'original_sound'"),
    media_filter: Optional[str] = Query("video", description="'video' to fetch video reels, 'audio' to fetch audio tracks"),
    limit: int = Query(15, ge=1, le=30),
) -> Dict[str, Any]:
    """Discover Instagram video reels (strictly excluding static images) or trending audio tracks."""
    config = get_config()
    db = get_db(config)

    q_str = query.strip() if isinstance(query, str) else ""
    t_str = target.strip() if isinstance(target, str) else ""
    effective_query = q_str or t_str
    m_filter = media_filter if isinstance(media_filter, str) else "video"

    # Video discovery mode (default or requested)
    if m_filter == "video" or effective_query:
        video_discoverer = InstagramVideoDiscoverer(config, db)
        candidates, examined, skipped, limitations = video_discoverer.discover_videos(
            query=effective_query if effective_query else None,
            limit=limit,
        )
        items: List[Dict[str, Any]] = []
        for c in candidates:
            is_processed = db.is_video_processed(c.source_id, platform="instagram")
            items.append({
                "source_id": c.source_id,
                "video_id": c.source_id,
                "id": c.source_id,
                "title": c.title,
                "channel_name": c.channel_name or "Instagram Creator",
                "channel_title": c.channel_name or "Instagram Creator",
                "artist": c.channel_name or "Instagram Creator",
                "artist_name": c.channel_name or "Instagram Creator",
                "uploader": c.channel_name or "Instagram Creator",
                "creator": c.channel_name or "Instagram Creator",
                "canonical_url": c.canonical_url,
                "url": c.canonical_url,
                "thumbnail": c.thumbnail_url or f"https://i.ytimg.com/vi/{c.source_id}/hqdefault.jpg",
                "thumbnail_url": c.thumbnail_url or f"https://i.ytimg.com/vi/{c.source_id}/hqdefault.jpg",
                "duration_seconds": c.duration_seconds,
                "duration": c.duration_seconds,
                "is_video": True,
                "is_image": False,
                "media_type": "video",
                "platform": "instagram",
                "is_processed": is_processed,
            })
        return {
            "available": True,
            "account_id": config.instagram_account_id,
            "media_filter": "video",
            "total_examined": examined,
            "total_skipped": skipped,
            "total_found": len(items),
            "items": items,
            "discovered_videos": items,
            "tracks": items,
            "limitations": limitations,
        }

    # Audio discovery mode:
    if audio_type:
        config.instagram_audio_type = audio_type

    discoverer = InstagramAudioDiscoverer(config, db)
    is_available, error_msg = discoverer.check_api_availability()

    if not is_available:
        return {
            "available": False,
            "reason": error_msg or "Instagram API access is unconfigured or unauthorized",
            "account_id": config.instagram_account_id,
            "audio_type": config.instagram_audio_type,
            "media_filter": "audio",
            "total_found": 0,
            "items": [],
            "discovered_videos": [],
            "tracks": [],
            "limitations": [error_msg] if error_msg else [],
        }

    try:
        candidates, examined, skipped, limitations = discoverer.discover_trending_audio(limit=limit)
        items = []
        for c in candidates:
            is_processed = db.is_video_processed(c.source_id, platform="instagram")
            is_sad = is_sad_song(c.title, c.artist)
            is_rap, rap_reason = is_rap_track(c.title, c.artist)
            items.append({
                "source_id": c.source_id,
                "audio_asset_id": c.source_id,
                "id": c.source_id,
                "title": c.title,
                "artist": c.artist,
                "artist_name": c.artist,
                "canonical_url": c.canonical_url,
                "url": c.canonical_url,
                "audio_url": c.audio_url,
                "preview_url": c.audio_url,
                "has_downloadable_stream": bool(c.audio_url),
                "duration_seconds": c.duration_seconds,
                "duration": c.duration_seconds,
                "popularity_score": c.popularity_score,
                "reel_count": c.reel_count,
                "trend_rank": c.trend_rank,
                "is_authorized": c.is_authorized,
                "is_sad": is_sad,
                "is_rap": is_rap,
                "rap_reason": rap_reason if is_rap else None,
                "is_processed": is_processed,
                "platform": "instagram",
                "media_type": "audio",
            })

        return {
            "available": True,
            "account_id": config.instagram_account_id,
            "audio_type": config.instagram_audio_type,
            "media_filter": "audio",
            "total_examined": examined,
            "total_skipped": skipped,
            "total_found": len(items),
            "items": items,
            "discovered_videos": items,
            "tracks": items,
            "limitations": limitations,
        }
    except Exception as e:
        logger.error(f"Instagram audio discovery failed: {e}", exc_info=True)
        return {
            "available": False,
            "reason": f"Instagram discovery failed: {e}",
            "account_id": config.instagram_account_id,
            "audio_type": config.instagram_audio_type,
            "media_filter": "audio",
            "total_found": 0,
            "items": [],
            "discovered_videos": [],
            "tracks": [],
            "limitations": [str(e)],
        }


# ---------------------------------------------------------------------------
# Pipeline Execution & Direct Download
# ---------------------------------------------------------------------------


def _run_pipeline_worker(job_id: str, cfg: AppConfig, channel: Optional[str], limit: Optional[int], source: str) -> None:
    """Thread worker executing full PodFetch pipeline and updating job state."""
    job = _active_jobs[job_id]
    job["status"] = "RUNNING"
    try:
        exit_code = execute_pipeline(
            config=cfg,
            cli_channel=channel,
            cli_limit=limit,
            cli_source=source,
        )
        job["status"] = "COMPLETED" if exit_code == 0 else "FAILED"
        job["exit_code"] = exit_code
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        job["status"] = "FAILED"
        job["error"] = str(e)
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.error(f"Pipeline job {job_id} encountered fatal error: {e}", exc_info=True)


@app.post("/api/jobs/run")
def start_pipeline_job(req: RunPipelineRequest) -> Dict[str, Any]:
    """Trigger an end-to-end PodFetch discovery and download pipeline run."""
    config = get_config()
    if req.dry_run:
        config.dry_run = True

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    _active_jobs[job_id] = {
        "job_id": job_id,
        "source": req.source,
        "limit": req.limit,
        "channel": req.channel,
        "dry_run": req.dry_run,
        "status": "QUEUED",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "error": None,
    }

    thread = threading.Thread(
        target=_run_pipeline_worker,
        args=(job_id, config, req.channel, req.limit, req.source),
        daemon=True,
    )
    thread.start()

    return {
        "success": True,
        "job_id": job_id,
        "message": f"Pipeline job {job_id} started for source '{req.source}'.",
    }


@app.get("/api/jobs")
def get_jobs_list(
    status: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Alias returning jobs from database matching library records."""
    records = get_library_records(platform=platform, status=status, search=None, limit=limit, offset=offset)
    return {
        "total": records["total"],
        "jobs": records["items"],
        "limit": records["limit"],
        "offset": records["offset"],
    }


@app.get("/api/jobs/active")
def get_active_jobs_endpoint() -> Dict[str, Any]:
    """Return active running background jobs."""
    jobs_list = sorted(_active_jobs.values(), key=lambda j: j["started_at"], reverse=True)
    return {
        "active_jobs": jobs_list,
        "total": len(jobs_list),
    }


@app.post("/api/jobs/retry-failed")
def retry_failed_jobs_alias(req: Optional[RetryFailedRequest] = None) -> Dict[str, Any]:
    """Retry failed jobs alias."""
    return retry_failed_jobs(req or RetryFailedRequest())


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Fetch status and outcome of an active or recent job."""
    if job_id not in _active_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return _active_jobs[job_id]


@app.post("/api/download/direct")
def direct_download(req: DirectDownloadRequest) -> Dict[str, Any]:
    """Download a single discovered video or audio track directly and upload to Google Drive."""
    config = get_config()
    db = get_db(config)

    # 1. Register candidate
    cand = VideoCandidate(
        youtube_video_id=req.source_id,
        channel_id=req.channel_name or req.platform,
        channel_name=req.channel_name or req.platform.capitalize(),
        title=req.title,
        youtube_url=req.canonical_url,
        platform=req.platform,
        source_id=req.source_id,
        canonical_url=req.canonical_url,
        duration_seconds=req.duration_seconds,
        artist=req.artist,
        audio_url=req.audio_url,
        thumbnail_url=req.thumbnail_url,
        search_keyword=req.search_keyword,
    )

    db.upsert_video(
        source_id=cand.source_id,
        title=cand.title,
        canonical_url=cand.canonical_url,
        platform=cand.platform,
        channel_id=cand.channel_id,
        channel_name=cand.channel_name,
        duration=cand.duration_seconds,
        status=VideoStatus.DISCOVERED,
        search_keyword=cand.search_keyword,
    )

    try:
        if req.platform == "instagram" and req.media_type != "video":
            downloader = InstagramAudioDownloader(config)
            audio_path, meta_path = downloader.download_audio(cand)
            downloaded_at = datetime.now(timezone.utc).isoformat()
            db.update_status(
                source_id=cand.source_id,
                platform="instagram",
                status=VideoStatus.DOWNLOADED,
                downloaded_at=downloaded_at,
            )

            # Automated Google Drive upload
            drive_file_id = None
            drive_path = None
            if config.google_drive_folder_id:
                try:
                    drive_uploader = GoogleDriveUploader(config)
                    clean_filename = generate_source_filename(
                        platform="instagram",
                        keyword_or_channel=cand.artist or cand.channel_name or "audio",
                        source_id=cand.source_id,
                        extension="mp3",
                    )
                    drive_file_id, drive_path = drive_uploader.upload_file(
                        file_path=audio_path,
                        custom_filename=clean_filename,
                        platform="instagram",
                        mimetype="audio/mpeg",
                        description=f"Instagram Trending Audio: {cand.title} by {cand.artist}",
                    )
                    if meta_path and meta_path.exists():
                        drive_uploader.upload_file(
                            file_path=meta_path,
                            custom_filename=meta_path.name,
                            platform="instagram",
                            mimetype="application/json",
                            description=f"Instagram Trending Audio Metadata: {cand.title}",
                        )
                except Exception as upload_err:
                    logger.error(f"Google Drive upload failed for Instagram audio {cand.title}: {upload_err}", exc_info=True)

            if drive_file_id:
                uploaded_at = datetime.now(timezone.utc).isoformat()
                db.update_status(
                    source_id=cand.source_id,
                    platform="instagram",
                    status=VideoStatus.UPLOADED,
                    drive_file_id=drive_file_id,
                    drive_path=drive_path,
                    uploaded_at=uploaded_at,
                )

            # Update audio manifest
            try:
                manifest_manager = AudioManifestManager(config.instagram_audio_manifest_path)
                manifest_manager.add_or_update_track(
                    audio_id=cand.source_id,
                    title=cand.title,
                    artist=cand.artist or "Instagram",
                    source_url=cand.canonical_url or "",
                    audio_file=audio_path.name,
                    local_path=str(audio_path),
                    drive_file_id=drive_file_id,
                    drive_path=drive_path,
                    duration_seconds=cand.duration_seconds,
                    status="UPLOADED" if drive_file_id else "DOWNLOADED",
                )
            except Exception as m_err:
                logger.warning(f"Audio manifest update failed: {m_err}")

            return {
                "success": True,
                "status": "UPLOADED" if drive_file_id else "DOWNLOADED",
                "message": f"Successfully processed '{req.title}'" + (f" and uploaded to Google Drive ({drive_file_id})" if drive_file_id else ""),
                "filename": audio_path.name,
                "file_size": audio_path.stat().st_size if audio_path.exists() else 0,
                "drive_file_id": drive_file_id,
                "drive_path": drive_path,
            }

        elif req.platform == "pinterest":
            p_downloader = PinterestDownloader(config)
            vid_path = p_downloader.download_video(cand)
            downloaded_at = datetime.now(timezone.utc).isoformat()
            db.update_status(
                source_id=cand.source_id,
                platform="pinterest",
                status=VideoStatus.DOWNLOADED,
                downloaded_at=downloaded_at,
            )

            # Automated Google Drive upload
            drive_file_id = None
            drive_path = None
            if config.google_drive_folder_id:
                try:
                    drive_uploader = GoogleDriveUploader(config)
                    clean_filename = generate_source_filename(
                        platform="pinterest",
                        keyword_or_channel=cand.search_keyword or cand.channel_name or "pinterest",
                        source_id=cand.source_id,
                        extension="mp4",
                    )
                    drive_file_id, drive_path = drive_uploader.upload_video(
                        vid_path, custom_filename=clean_filename, platform="pinterest"
                    )
                except Exception as upload_err:
                    logger.error(f"Google Drive upload failed for Pinterest video {cand.title}: {upload_err}", exc_info=True)

            if drive_file_id:
                uploaded_at = datetime.now(timezone.utc).isoformat()
                db.update_status(
                    source_id=cand.source_id,
                    platform="pinterest",
                    status=VideoStatus.UPLOADED,
                    drive_file_id=drive_file_id,
                    drive_path=drive_path,
                    uploaded_at=uploaded_at,
                )

            return {
                "success": True,
                "status": "UPLOADED" if drive_file_id else "DOWNLOADED",
                "message": f"Successfully processed Pinterest video '{req.title}'" + (f" and uploaded to Google Drive ({drive_file_id})" if drive_file_id else ""),
                "filename": vid_path.name,
                "file_size": vid_path.stat().st_size if vid_path.exists() else 0,
                "drive_file_id": drive_file_id,
                "drive_path": drive_path,
            }

        elif req.platform in ("youtube", "instagram"):
            y_downloader = VideoDownloader(config)
            vid_path = y_downloader.download_video(cand)
            downloaded_at = datetime.now(timezone.utc).isoformat()
            db.update_status(
                source_id=cand.source_id,
                platform=req.platform,
                status=VideoStatus.DOWNLOADED,
                downloaded_at=downloaded_at,
            )

            # Automated Google Drive upload
            drive_file_id = None
            drive_path = None
            if config.google_drive_folder_id:
                try:
                    drive_uploader = GoogleDriveUploader(config)
                    clean_filename = generate_source_filename(
                        platform=req.platform,
                        keyword_or_channel=cand.channel_name or cand.search_keyword or "video",
                        source_id=cand.source_id,
                        extension="mp4",
                    )
                    drive_file_id, drive_path = drive_uploader.upload_video(
                        vid_path, custom_filename=clean_filename, platform=req.platform
                    )
                except Exception as upload_err:
                    logger.error(f"Google Drive upload failed for {req.platform} video {cand.title}: {upload_err}", exc_info=True)

            if drive_file_id:
                uploaded_at = datetime.now(timezone.utc).isoformat()
                db.update_status(
                    source_id=cand.source_id,
                    platform=req.platform,
                    status=VideoStatus.UPLOADED,
                    drive_file_id=drive_file_id,
                    drive_path=drive_path,
                    uploaded_at=uploaded_at,
                )

            return {
                "success": True,
                "status": "UPLOADED" if drive_file_id else "DOWNLOADED",
                "message": f"Successfully processed {req.platform.capitalize()} video '{req.title}'" + (f" and uploaded to Google Drive ({drive_file_id})" if drive_file_id else ""),
                "filename": vid_path.name,
                "file_size": vid_path.stat().st_size if vid_path.exists() else 0,
                "drive_file_id": drive_file_id,
                "drive_path": drive_path,
            }

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported platform: {req.platform}")

    except Exception as e:
        db.update_status(
            source_id=cand.source_id,
            platform=cand.platform,
            status=VideoStatus.FAILED,
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")


# ---------------------------------------------------------------------------
# Google Drive Status
# ---------------------------------------------------------------------------


@app.get("/api/drive/status")
def get_drive_status() -> Dict[str, Any]:
    """Retrieve Google Drive connection health, destination folder, and recent uploads."""
    config = get_config()
    db = get_db(config)

    is_configured = bool(config.google_drive_folder_id)
    auth_success = False
    auth_type = "None"
    auth_error = None

    if is_configured:
        try:
            uploader = GoogleDriveUploader(config)
            uploader.authenticate()
            auth_success = True
            if config.google_service_account_file or config.google_service_account_json:
                auth_type = "Service Account"
            elif config.google_client_id and config.google_refresh_token:
                auth_type = "OAuth 2.0 Refresh Token"
            elif config.google_token_file or Path("token.json").exists():
                auth_type = "Authorized User Token (token.json)"
        except Exception as e:
            auth_error = str(e)

    # Fetch recent uploads from database
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, platform, source_id, title, drive_file_id, drive_path, uploaded_at, duration, canonical_url
            FROM videos
            WHERE status = 'UPLOADED'
            ORDER BY uploaded_at DESC
            LIMIT 15
            """
        )
        recent_uploads = [dict(r) for r in cursor.fetchall()]

    return {
        "configured": is_configured,
        "authenticated": auth_success,
        "auth_type": auth_type,
        "auth_error": auth_error,
        "destination_folder_id": config.google_drive_folder_id,
        "folder_id": config.google_drive_folder_id,
        "credentials_present": config.google_service_account_file is not None or Path("credentials.json").exists(),
        "token_present": Path("token.json").exists() or bool(config.google_token_file),
        "instagram_subfolder": config.instagram_drive_folder_name,
        "use_date_subfolders": config.use_date_subfolders,
        "subfolders": ["Podcasts", config.instagram_drive_folder_name],
        "recent_uploads": recent_uploads,
    }


@app.get("/api/instagram/status")
def get_instagram_status() -> Dict[str, Any]:
    """Return status of Instagram Graph API connection."""
    config = get_config()
    db = get_db(config)
    discoverer = InstagramAudioDiscoverer(config, db)
    is_available, error_msg = discoverer.check_api_availability()
    return {
        "configured": bool(config.instagram_account_id and config.instagram_access_token),
        "available": is_available,
        "error": error_msg,
        "account_id": config.instagram_account_id,
        "audio_type": config.instagram_audio_type,
        "drive_folder": config.instagram_drive_folder_name,
        "allow_rap": config.instagram_allow_rap,
        "prioritize_sad": config.instagram_prioritize_sad,
    }


# ---------------------------------------------------------------------------
# Jobs & Queue Compatibility Endpoints
# ---------------------------------------------------------------------------



def _resolve_video_target(
    url_or_keyword: str,
    platform_hint: str = "youtube",
    config: Optional[AppConfig] = None,
    db: Optional[Database] = None,
) -> DirectDownloadRequest:
    """Resolve an arbitrary URL or search keyword into a valid DirectDownloadRequest for YouTube or Pinterest."""
    cfg = config or get_config()
    database = db or get_db(cfg)
    target_str = url_or_keyword.strip()
    low = target_str.lower()

    # Normalize scheme if domain appears without http(s)://
    if not target_str.startswith("http://") and not target_str.startswith("https://"):
        if any(d in low for d in ("youtube.com", "youtu.be", "pinterest.com", "pin.it", "instagram.com", "instagr.am")) or target_str.startswith("www."):
            target_str = f"https://{target_str}"
            low = target_str.lower()

    # Determine platform
    if "pinterest.com" in low or "pin.it" in low:
        effective_platform = "pinterest"
    elif "instagram.com" in low or "instagr.am" in low:
        effective_platform = "instagram"
    elif "youtube.com" in low or "youtu.be" in low:
        effective_platform = "youtube"
    else:
        effective_platform = platform_hint.lower() if platform_hint else "youtube"

    if effective_platform == "instagram":
        if target_str.startswith("http://") or target_str.startswith("https://"):
            ydl_opts = {"extract_flat": True, "quiet": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(target_str, download=False)
                    if info.get("_type") == "image" or info.get("vcodec") == "none":
                        raise HTTPException(
                            status_code=400,
                            detail="This Instagram post is a static image photo. PodFetch only downloads video media and reels."
                        )
                    vid_id = str(info.get("id") or "ig_video")
                    return DirectDownloadRequest(
                        platform="instagram",
                        media_type="video",
                        source_id=vid_id,
                        title=info.get("title") or f"Instagram Video {vid_id}",
                        canonical_url=info.get("webpage_url") or target_str,
                        channel_name=info.get("uploader") or "Instagram",
                        duration_seconds=info.get("duration"),
                        thumbnail_url=info.get("thumbnail"),
                        search_keyword="instagram",
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    if "no video" in str(e).lower():
                        raise HTTPException(
                            status_code=400,
                            detail="This Instagram post is a static image photo. PodFetch only downloads video media and reels."
                        )
                    vid_id = f"ig_{uuid.uuid4().hex[:8]}"
                    return DirectDownloadRequest(
                        platform="instagram",
                        media_type="video",
                        source_id=vid_id,
                        title=f"Instagram Reel {vid_id}",
                        canonical_url=target_str,
                        channel_name="Instagram",
                        duration_seconds=30,
                        search_keyword="instagram",
                    )
        else:
            query = f"ytsearch1:{target_str} instagram reel"
            ydl_opts = {"extract_flat": True, "quiet": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    res = ydl.extract_info(query, download=False)
                    entries = res.get("entries", [])
                    if not entries:
                        raise HTTPException(status_code=404, detail=f"No Instagram video reels found for '{target_str}'.")
                    entry = entries[0]
                    vid_id = str(entry.get("id") or "ig_video")
                    return DirectDownloadRequest(
                        platform="instagram",
                        media_type="video",
                        source_id=vid_id,
                        title=entry.get("title") or f"Instagram Video {vid_id}",
                        canonical_url=entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                        channel_name=entry.get("uploader") or "Instagram",
                        duration_seconds=entry.get("duration"),
                        thumbnail_url=entry.get("thumbnail"),
                        search_keyword=target_str,
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Failed to find Instagram video: {e}")

    if effective_platform == "pinterest":
        # Resolve shortlinks (pin.it)
        if "pin.it" in low:
            try:
                import urllib.request
                req_head = urllib.request.Request(
                    target_str,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                with urllib.request.urlopen(req_head, timeout=10) as r:
                    resolved_url = r.geturl()
                    if "/pin/" in resolved_url:
                        target_str = resolved_url
                        low = target_str.lower()
            except Exception as e:
                logger.debug(f"pin.it redirect resolution notice: {e}")

        # Check if direct Pin URL or Pin ID
        pin_match = re.search(r"/pin/(\d+)", target_str)
        if pin_match or (target_str.isdigit() and len(target_str) >= 10):
            pin_id = pin_match.group(1) if pin_match else target_str
            p_disc = PinterestDiscoverer(cfg, database)
            title = f"Pinterest Pin {pin_id}"
            thumb = None
            dur = None
            try:
                details = p_disc.fetch_pin_details(pin_id)
                if details:
                    if details.title:
                        title = details.title
                    thumb = details.thumbnail_url
                    dur = details.duration_seconds
            except Exception:
                pass

            return DirectDownloadRequest(
                platform="pinterest",
                source_id=pin_id,
                title=title,
                canonical_url=f"https://www.pinterest.com/pin/{pin_id}/",
                channel_name="Pinterest",
                duration_seconds=dur,
                thumbnail_url=thumb,
                search_keyword="pinterest",
            )
        else:
            # It's a Pinterest keyword search term! (e.g. "nature", "aesthetics", "motivation")
            p_disc = PinterestDiscoverer(cfg, database)
            pins = p_disc.search_keyword(target_str)
            video_pins = [p for p in pins if p.is_video]
            chosen = video_pins[0] if video_pins else (pins[0] if pins else None)
            if not chosen:
                raise HTTPException(
                    status_code=404,
                    detail=f"No video Pins found on Pinterest for '{target_str}'. Try searching another keyword like 'nature aesthetic'."
                )
            return DirectDownloadRequest(
                platform="pinterest",
                source_id=chosen.pin_id,
                title=chosen.title or f"Pinterest {target_str} Video",
                canonical_url=chosen.canonical_url,
                channel_name="Pinterest",
                duration_seconds=chosen.duration_seconds,
                thumbnail_url=chosen.thumbnail_url,
                search_keyword=target_str,
            )

    # Otherwise YouTube:
    ydl_opts = {"extract_flat": True, "quiet": True}
    if target_str.startswith("http://") or target_str.startswith("https://"):
        # Direct video URL
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(target_str, download=False)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to probe YouTube URL: {e}")
            vid_id = info.get("id") or "video"
            title = info.get("title") or f"YouTube Video {vid_id}"
            uploader = info.get("uploader") or info.get("channel") or "YouTube"
            canonical_url = info.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"
            duration = info.get("duration")
            return DirectDownloadRequest(
                platform="youtube",
                source_id=vid_id,
                title=title,
                canonical_url=canonical_url,
                channel_name=uploader,
                duration_seconds=duration,
                thumbnail_url=info.get("thumbnail"),
                search_keyword=uploader,
            )
    else:
        # Search keyword on YouTube (e.g. "relaxing nature sound", "huberman podcast")
        query = f"ytsearch1:{target_str}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                res = ydl.extract_info(query, download=False)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to search YouTube: {e}")
            entries = res.get("entries", [])
            if not entries:
                raise HTTPException(status_code=404, detail=f"No YouTube videos found matching '{target_str}'.")
            entry = entries[0]
            vid_id = entry.get("id") or "video"
            title = entry.get("title") or f"YouTube Video {vid_id}"
            uploader = entry.get("uploader") or entry.get("channel") or "YouTube"
            canonical_url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}"
            duration = entry.get("duration")
            return DirectDownloadRequest(
                platform="youtube",
                source_id=vid_id,
                title=title,
                canonical_url=canonical_url,
                channel_name=uploader,
                duration_seconds=duration,
                thumbnail_url=entry.get("thumbnail"),
                search_keyword=target_str,
            )


@app.post("/api/download/video")
def download_video_endpoint(payload: VideoDownloadPayload) -> Dict[str, Any]:
    """Download YouTube or Pinterest video payload with automated Google Drive upload."""
    config = get_config()
    db = get_db(config)
    job_id = f"vid-{uuid.uuid4().hex[:8]}"

    # Initial target detection
    platform_hint = payload.platform or "youtube"
    low = payload.url.lower()
    if "pinterest.com" in low or "pin.it" in low:
        platform_hint = "pinterest"
    elif "instagram.com" in low or "instagr.am" in low:
        platform_hint = "instagram"
    elif "youtube.com" in low or "youtu.be" in low:
        platform_hint = "youtube"

    _active_jobs[job_id] = {
        "job_id": job_id,
        "platform": platform_hint,
        "title": payload.title or payload.url,
        "url": payload.url,
        "status": "RUNNING",
        "progress": "Starting video download & Google Drive upload...",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "error": None,
        "drive_file_id": None,
    }

    def _worker():
        try:
            req = _resolve_video_target(payload.url, platform_hint=platform_hint, config=config, db=db)
            if payload.title:
                req.title = payload.title
            _active_jobs[job_id]["title"] = req.title
            _active_jobs[job_id]["platform"] = req.platform
            _active_jobs[job_id]["url"] = req.canonical_url
            _active_jobs[job_id]["progress"] = f"Downloading {req.platform} media..."

            result = direct_download(req)
            _active_jobs[job_id]["status"] = "COMPLETED"
            _active_jobs[job_id]["progress"] = "Completed and uploaded to Google Drive"
            _active_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            _active_jobs[job_id]["drive_file_id"] = result.get("drive_file_id")
            _active_jobs[job_id]["filename"] = result.get("filename")
            _active_jobs[job_id]["drive_path"] = result.get("drive_path")
        except Exception as e:
            logger.error(f"Download video failed for job {job_id}: {e}", exc_info=True)
            _active_jobs[job_id]["status"] = "FAILED"
            _active_jobs[job_id]["error"] = str(e)
            _active_jobs[job_id]["progress"] = f"Failed: {e}"
            _active_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return {
        "status": "queued",
        "job_id": job_id,
        "message": f"Download initiated for {platform_hint} video.",
    }


@app.post("/api/download/instagram-audio")
def download_instagram_audio_endpoint(payload: InstagramAudioPayload) -> Dict[str, Any]:
    """Download Instagram trending audio payload with automated Google Drive upload."""
    config = get_config()
    job_id = f"audio-{uuid.uuid4().hex[:8]}"

    _active_jobs[job_id] = {
        "job_id": job_id,
        "platform": "instagram",
        "title": payload.title,
        "url": payload.audio_url or f"https://www.instagram.com/reels/audio/{payload.audio_asset_id}",
        "status": "RUNNING",
        "progress": "Downloading audio & synchronizing to Drive...",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "error": None,
        "drive_file_id": None,
    }

    def _worker():
        try:
            req = DirectDownloadRequest(
                platform="instagram",
                source_id=payload.audio_asset_id,
                title=payload.title,
                canonical_url=payload.audio_url or f"https://www.instagram.com/reels/audio/{payload.audio_asset_id}",
                audio_url=payload.audio_url,
                artist=payload.artist,
            )
            result = direct_download(req)
            _active_jobs[job_id]["status"] = "COMPLETED"
            _active_jobs[job_id]["progress"] = "Completed and uploaded to Google Drive"
            _active_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
            _active_jobs[job_id]["drive_file_id"] = result.get("drive_file_id")
            _active_jobs[job_id]["filename"] = result.get("filename")
            _active_jobs[job_id]["drive_path"] = result.get("drive_path")
        except Exception as e:
            logger.error(f"Download audio failed for job {job_id}: {e}", exc_info=True)
            _active_jobs[job_id]["status"] = "FAILED"
            _active_jobs[job_id]["error"] = str(e)
            _active_jobs[job_id]["progress"] = f"Failed: {e}"
            _active_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return {
        "status": "queued",
        "job_id": job_id,
        "message": f"Instagram audio sync initiated for '{payload.title}'.",
    }


# POST Discovery Endpoints
@app.post("/api/discover/youtube")
def discover_youtube_post(payload: YouTubeDiscoverPayload) -> Dict[str, Any]:
    """POST endpoint for YouTube discovery."""
    ch = payload.channel or (payload.channels[0] if payload.channels else None)
    res = discover_youtube(channel=ch, limit=payload.max_videos)
    return {
        "status": "error" if "error" in res else "ok",
        "message": res.get("error"),
        "discovered_videos": res.get("items", []),
        "total_found": res.get("total_found", 0),
    }


@app.post("/api/discover/pinterest")
def discover_pinterest_post(payload: PinterestDiscoverPayload) -> Dict[str, Any]:
    """POST endpoint for Pinterest discovery."""
    res = discover_pinterest(keyword=payload.keyword, limit=payload.max_videos)
    return {
        "status": "error" if "error" in res else "ok",
        "message": res.get("error"),
        "discovered_videos": res.get("items", []),
        "total_found": res.get("total_found", 0),
    }


@app.post("/api/discover/instagram")
def discover_instagram_post(payload: InstagramDiscoverPayload) -> Dict[str, Any]:
    """POST endpoint for Instagram discovery."""
    q = payload.query or payload.target
    res = discover_instagram(
        query=q,
        target=None,
        audio_type=payload.audio_type,
        media_filter=payload.media_filter or "video",
        limit=payload.limit or 15,
    )
    items = res.get("items", [])
    return {
        "status": "error" if not res.get("available") and "reason" in res and not items else "ok",
        "message": res.get("reason"),
        "tracks": items,
        "discovered_videos": items,
        "items": items,
        "total_found": len(items),
    }


# ---------------------------------------------------------------------------
# Settings & Configuration
# ---------------------------------------------------------------------------


@app.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    """Get safe system settings without exposing secrets."""
    config = get_config()

    return {
        "enabled_sources": config.enabled_sources,
        "sources_enabled": config.enabled_sources,
        "youtube_enabled": config.youtube_enabled,
        "pinterest_enabled": config.pinterest_enabled,
        "instagram_enabled": config.instagram_enabled,
        "youtube_channels": config.youtube_channels,
        "pinterest_keywords": config.pinterest_keywords,
        "video_filter": {
            "min_duration": config.min_video_duration_seconds,
            "max_duration": config.max_video_duration_seconds,
            "min_resolution": config.min_video_resolution,
            "max_video_size_mb": 500,
            "max_videos_per_channel": config.max_videos_per_run,
        },
        "instagram": {
            "enabled": config.instagram_enabled,
            "account_id": config.instagram_account_id,
            "drive_folder_name": config.instagram_drive_folder_name,
            "audio_type": config.instagram_audio_type,
            "allow_rap": config.instagram_allow_rap,
            "prioritize_sad": config.instagram_prioritize_sad,
            "token_configured": bool(config.instagram_access_token),
        },
        "google_drive": {
            "configured": bool(config.google_drive_folder_id),
            "folder_id": config.google_drive_folder_id,
        },
        "min_videos_per_run": config.min_videos_per_run,
        "max_videos_per_run": config.max_videos_per_run,
        "min_video_resolution": config.min_video_resolution,
        "prefer_vertical": config.prefer_vertical,
        "min_video_duration_seconds": config.min_video_duration_seconds,
        "max_video_duration_seconds": config.max_video_duration_seconds,
        "min_audio_duration_seconds": config.min_audio_duration_seconds,
        "max_audio_duration_seconds": config.max_audio_duration_seconds,
        "instagram_audio_type": config.instagram_audio_type,
        "instagram_allow_rap": config.instagram_allow_rap,
        "instagram_prioritize_sad": config.instagram_prioritize_sad,
        "instagram_account_id": config.instagram_account_id,
        "instagram_token_configured": bool(config.instagram_access_token),
        "drive_configured": bool(config.google_drive_folder_id),
        "drive_folder_id": config.google_drive_folder_id,
        "download_quality": config.download_quality,
        "dry_run": config.dry_run,
    }


@app.get("/api/logs")
def get_system_logs(lines: int = Query(80, ge=10, le=500)) -> Dict[str, Any]:
    """Return recent log lines from project log files."""
    config = get_config()
    log_file = config.log_dir / "podfetch.log"
    if not log_file.exists():
        # Check for any log file in log_dir
        log_files = sorted(config.log_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if log_files:
            log_file = log_files[0]
        else:
            return {"lines": ["Log file has not been created yet."], "logs": ["Log file has not been created yet."]}

    try:
        content = log_file.read_text(encoding="utf-8", errors="replace")
        all_lines = content.strip().split("\n")
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return {
            "log_file": log_file.name,
            "total_lines": len(all_lines),
            "lines": tail,
            "logs": tail,
        }
    except Exception as e:
        return {"error": str(e), "lines": [], "logs": []}


# ---------------------------------------------------------------------------
# Nature Cinematic Reel Maker Endpoints
# ---------------------------------------------------------------------------

from nature.models import (
    CompositionMode,
    JobStage,
    NatureCategory,
    NatureProfile,
    NatureReel,
    NatureTemplateConfig,
    ReelStatus,
    TEMPLATE_MINIMAL_WHITE_SERIF,
    TEMPLATE_THOUGHT_REEL,
)
from nature.pipeline import NaturePipeline
from nature.profile import DEFAULT_EXCLUDED_TERMS, DEFAULT_NATURE_CATEGORIES, ProfileManager
from nature.template import AVAILABLE_FONTS, NatureTemplateRenderer
from quran.key_rotator import get_key_rotator

_nature_pipeline_instance: Optional[NaturePipeline] = None


def get_nature_pipeline() -> NaturePipeline:
    global _nature_pipeline_instance
    if _nature_pipeline_instance is None:
        cfg = get_config()
        db = get_db(cfg)
        _nature_pipeline_instance = NaturePipeline(config=cfg, db=db)
    return _nature_pipeline_instance


class NatureProfileUpdateRequest(BaseModel):
    categories: Optional[List[str]] = None
    custom_keywords: Optional[Dict[str, List[str]]] = None
    excluded_terms: Optional[List[str]] = None
    search_limit: Optional[int] = Field(default=15, ge=1, le=50)
    daily_processing_limit: Optional[int] = Field(default=10, ge=1, le=100)
    min_quality_score: Optional[float] = Field(default=65.0, ge=0.0, le=100.0)
    recency_preference: Optional[str] = "any"
    strict_recency: Optional[bool] = False
    search_mood: Optional[str] = "cinematic"
    season: Optional[str] = "any"
    preferred_orientation: Optional[str] = "vertical_9_16"
    is_active: Optional[bool] = True


class NatureDraftUpdateRequest(BaseModel):
    thought_text: str
    caption: str
    hashtags: List[str]


class NatureRerenderRequest(BaseModel):
    thought_text: Optional[str] = None
    template_name: Optional[str] = None
    composition_mode: Optional[str] = "crop"
    color_preset: Optional[str] = "restrained_warm"
    color_intensity: Optional[float] = 1.0
    font_path: Optional[str] = None
    font_size: Optional[int] = 44
    line_spacing: Optional[int] = 24
    shadow_strength: Optional[float] = 0.65
    target_duration: Optional[float] = None
    source_audio_volume: Optional[float] = 1.0
    music_path: Optional[str] = None
    music_volume: Optional[float] = 0.4


class NatureRunRequest(BaseModel):
    category: Optional[str] = None
    keyword: Optional[str] = None
    mood: Optional[str] = None
    season: Optional[str] = None
    recency_preference: Optional[str] = "any"
    strict_recency: Optional[bool] = False
    preferred_orientation: Optional[str] = "vertical_9_16"
    min_quality_score: Optional[float] = None
    search_limit: Optional[int] = Field(default=15, ge=1, le=50)
    excluded_terms: Optional[List[str]] = None
    max_reels: int = Field(default=1, ge=1, le=5)
    composition_mode: str = Field(default="crop")
    template_name: Optional[str] = None
    custom_thought: Optional[str] = None
    target_duration: Optional[float] = Field(default=12.0, ge=5.0, le=30.0)
    font_size: Optional[int] = Field(default=44, ge=24, le=72)
    line_spacing: Optional[int] = Field(default=24, ge=10, le=60)
    music_path: Optional[str] = None
    music_volume: Optional[float] = Field(default=0.4, ge=0.0, le=2.0)
    source_audio_volume: Optional[float] = Field(default=1.0, ge=0.0, le=2.0)


@app.get("/api/nature/categories")
def get_nature_categories() -> Dict[str, Any]:
    """Get predefined and active nature categories with keyword variations."""
    pipe = get_nature_pipeline()
    cats = pipe.profile_manager.get_categories()
    return {
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "keywords": c.keywords,
            }
            for c in cats.values()
        ]
    }


@app.get("/api/nature/profile")
def get_nature_profile_endpoint() -> Dict[str, Any]:
    """Get the active Nature Cinematic Reels profile and AI status without exposing secrets."""
    pipe = get_nature_pipeline()
    prof = pipe.profile_manager.profile
    rotator = get_key_rotator()

    # Redacted AI key status
    active_keys_count = len(rotator._keys)
    masked_key = (
        f"{rotator.get_current_key()[:8]}...{rotator.get_current_key()[-4:]}"
        if rotator.has_keys
        else None
    )

    return {
        "profile": prof.to_dict(),
        "ai_status": {
            "has_groq_key": rotator.has_keys,
            "active_keys_count": active_keys_count,
            "masked_key": masked_key,
            "provider": "groq" if rotator.has_keys else "curated_library",
            "model": "openai/gpt-oss-20b" if rotator.has_keys else "curated-fallback-engine",
        },
        "default_categories": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "keywords": c.keywords,
            }
            for c in DEFAULT_NATURE_CATEGORIES.values()
        ],
    }


@app.put("/api/nature/profile")
def update_nature_profile_endpoint(req: NatureProfileUpdateRequest) -> Dict[str, Any]:
    """Update Nature profile settings in SQLite."""
    pipe = get_nature_pipeline()
    prof = pipe.profile_manager.profile

    if req.categories is not None:
        prof.categories = req.categories
    if req.custom_keywords is not None:
        prof.custom_keywords = req.custom_keywords
    if req.excluded_terms is not None:
        prof.excluded_terms = req.excluded_terms
    if req.search_limit is not None:
        prof.search_limit = req.search_limit
    if req.daily_processing_limit is not None:
        prof.daily_processing_limit = req.daily_processing_limit
    if req.min_quality_score is not None:
        prof.min_quality_score = req.min_quality_score
    if req.recency_preference is not None:
        prof.recency_preference = req.recency_preference
    if req.strict_recency is not None:
        prof.strict_recency = req.strict_recency
    if req.search_mood is not None:
        prof.search_mood = req.search_mood
    if req.season is not None:
        prof.season = req.season
    if req.preferred_orientation is not None:
        prof.preferred_orientation = req.preferred_orientation
    if req.is_active is not None:
        prof.is_active = req.is_active

    prof.updated_at = datetime.now(timezone.utc).isoformat()
    pipe.db.save_nature_profile(prof.to_dict())
    pipe.reload_profile()

    return {"status": "success", "profile": prof.to_dict()}


@app.get("/api/nature/candidates")
def get_nature_candidates_endpoint(
    category: Optional[str] = None, limit: int = Query(50, ge=1, le=100)
) -> Dict[str, Any]:
    """Get discovered nature footage candidates and quality scores."""
    pipe = get_nature_pipeline()
    candidates = pipe.db.get_nature_candidates(category=category, limit=limit)
    return {"candidates": candidates, "total": len(candidates)}


@app.get("/api/nature/reels")
def get_nature_reels_endpoint(
    status: Optional[str] = None, limit: int = Query(50, ge=1, le=100)
) -> Dict[str, Any]:
    """Get nature reels (PENDING review, APPROVED, or REJECTED)."""
    pipe = get_nature_pipeline()
    reels = pipe.db.get_nature_reels(status=status, limit=limit)
    return {"reels": reels, "total": len(reels)}


@app.get("/api/nature/reels/{reel_id}")
def get_single_nature_reel(reel_id: int) -> Dict[str, Any]:
    """Get single nature reel by ID."""
    pipe = get_nature_pipeline()
    reel = pipe.db.get_nature_reel_by_id(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail=f"Reel ID {reel_id} not found")
    return {"reel": reel}


@app.put("/api/nature/reels/{reel_id}/draft")
def update_nature_reel_draft_endpoint(
    reel_id: int, req: NatureDraftUpdateRequest
) -> Dict[str, Any]:
    """Update editable thought text, caption, and hashtags before approval."""
    pipe = get_nature_pipeline()
    reel = pipe.db.get_nature_reel_by_id(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail=f"Reel ID {reel_id} not found")

    ok = pipe.db.update_nature_reel_draft(
        reel_id=reel_id,
        thought_text=req.thought_text,
        caption=req.caption,
        hashtags=req.hashtags,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update reel draft")

    updated = pipe.db.get_nature_reel_by_id(reel_id)
    return {"status": "success", "reel": updated}


@app.post("/api/nature/reels/{reel_id}/approve")
def approve_nature_reel_endpoint(reel_id: int) -> Dict[str, Any]:
    """Mark a reel as APPROVED for publishing."""
    pipe = get_nature_pipeline()
    reel = pipe.db.get_nature_reel_by_id(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail=f"Reel ID {reel_id} not found")

    pipe.db.update_nature_reel_status(reel_id, ReelStatus.APPROVED.value)
    return {"status": "success", "reel_id": reel_id, "reel_status": ReelStatus.APPROVED.value}


@app.post("/api/nature/reels/{reel_id}/reject")
def reject_nature_reel_endpoint(reel_id: int) -> Dict[str, Any]:
    """Mark a reel as REJECTED."""
    pipe = get_nature_pipeline()
    reel = pipe.db.get_nature_reel_by_id(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail=f"Reel ID {reel_id} not found")

    pipe.db.update_nature_reel_status(reel_id, ReelStatus.REJECTED.value)
    return {"status": "success", "reel_id": reel_id, "reel_status": ReelStatus.REJECTED.value}


@app.get("/api/nature/templates")
def get_nature_templates_endpoint() -> Dict[str, Any]:
    """Return available template presets and system fonts for Nature Reels."""
    return {
        "templates": [
            {
                "id": TEMPLATE_MINIMAL_WHITE_SERIF,
                "name": TEMPLATE_MINIMAL_WHITE_SERIF,
                "description": "Full-screen nature footage with elegant white serif typography, soft drop shadow, centered middle-to-lower-middle, 4-7 lines, and calm pacing.",
                "default_font_size": 44,
                "default_line_spacing": 24,
                "default_composition": "crop",
                "default_shadow_strength": 0.65,
                "default_duration": 12.0,
                "enable_scrim": False,
            },
            {
                "id": TEMPLATE_THOUGHT_REEL,
                "name": TEMPLATE_THOUGHT_REEL,
                "description": "Cinematic nature reel with semi-transparent contrast scrim band and warm color grading.",
                "default_font_size": 44,
                "default_line_spacing": 20,
                "default_composition": "crop",
                "default_shadow_strength": 0.80,
                "default_duration": 10.0,
                "enable_scrim": True,
            },
        ],
        "available_fonts": [
            {"path": f, "name": Path(f).stem} for f in AVAILABLE_FONTS if Path(f).exists()
        ],
    }


@app.post("/api/nature/reels/{reel_id}/rerender")
def rerender_nature_reel_endpoint(
    reel_id: int, req: NatureRerenderRequest, background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """Re-render an existing reel with updated thought text, composition mode, or style."""
    pipe = get_nature_pipeline()
    reel = pipe.db.get_nature_reel_by_id(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail=f"Reel ID {reel_id} not found")

    orig_path = reel.get("original_video_path")
    out_path = reel.get("rendered_reel_path")
    if not orig_path or not Path(orig_path).exists():
        raise HTTPException(
            status_code=400,
            detail=f"Original source video not found on disk at {orig_path}",
        )

    text_to_render = req.thought_text or reel.get("thought_text")

    def _do_rerender():
        tpl_name = req.template_name or reel.get("template_name") or TEMPLATE_MINIMAL_WHITE_SERIF
        tpl_cfg = NatureTemplateConfig.from_preset(tpl_name)
        comp_mode = req.composition_mode or reel.get("composition_mode", "crop")
        tpl_cfg.composition_mode = comp_mode

        if req.font_size:
            tpl_cfg.font_size = req.font_size
        if req.line_spacing is not None:
            tpl_cfg.line_spacing = req.line_spacing
        if req.shadow_strength is not None:
            tpl_cfg.shadow_strength = req.shadow_strength
        if req.color_intensity is not None:
            tpl_cfg.color_grading_intensity = req.color_intensity
        if req.color_preset:
            tpl_cfg.color_grade_preset = req.color_preset
        if req.font_path:
            tpl_cfg.font_path = req.font_path
        if req.music_path:
            tpl_cfg.music_path = req.music_path
        if req.music_volume is not None:
            tpl_cfg.music_volume = req.music_volume
        if req.source_audio_volume is not None:
            tpl_cfg.source_audio_volume = req.source_audio_volume

        dur = req.target_duration or float(reel.get("duration_seconds", 12.0))

        renderer = NatureTemplateRenderer(config=tpl_cfg)
        ok, err = renderer.render_reel(
            input_video_path=orig_path,
            thought_text=text_to_render,
            output_reel_path=out_path,
            target_duration=dur,
            composition_mode=comp_mode,
            template_config=tpl_cfg,
        )
        if ok:
            if reel.get("thumbnail_path"):
                renderer.generate_thumbnail(out_path, reel["thumbnail_path"], timestamp=1.5)
            # Update SQLite record
            pipe.db.save_nature_reel({
                **reel,
                "thought_text": text_to_render,
                "template_name": tpl_name,
                "composition_mode": comp_mode,
                "duration_seconds": dur,
            })
            logger.info(f"Re-render succeeded for reel {reel_id}")
        else:
            logger.error(f"Re-render failed for reel {reel_id}: {err}")

    background_tasks.add_task(_do_rerender)
    return {
        "status": "rerendering_started",
        "reel_id": reel_id,
        "composition_mode": req.composition_mode,
    }


@app.get("/api/nature/preview-keywords")
def preview_nature_keywords_endpoint(
    category: Optional[str] = None,
    mood: Optional[str] = None,
    season: Optional[str] = None,
    orientation: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate live search query preview, available rotation pool, and options."""
    pipe = get_nature_pipeline()
    eff_cat = category or (pipe.profile_manager.profile.categories[0] if pipe.profile_manager.profile.categories else "autumn_forest")
    eff_mood = (mood or pipe.profile_manager.profile.search_mood or "cinematic").strip()
    eff_season = (season or pipe.profile_manager.profile.season or "any").strip()
    eff_orient = (orientation or pipe.profile_manager.profile.preferred_orientation or "vertical_9_16").strip()

    resolved_cat, base_kw, query = pipe.profile_manager.generate_search_query(
        category_id=eff_cat,
        mood=eff_mood,
        season=eff_season,
        orientation=eff_orient,
        randomize=False,
    )
    categories = pipe.profile_manager.get_categories()
    cat_obj = categories.get(resolved_cat) or categories.get(eff_cat)
    cat_name = cat_obj.name if cat_obj else eff_cat.replace("_", " ").title()
    all_kw = cat_obj.keywords if cat_obj else []

    sample_queries = []
    for sample_kw in all_kw[:4]:
        _, _, sq = pipe.profile_manager.generate_search_query(
            category_id=resolved_cat,
            keyword=sample_kw,
            mood=eff_mood,
            season=eff_season,
            orientation=eff_orient,
        )
        sample_queries.append(sq)

    return {
        "category": resolved_cat,
        "category_name": cat_name,
        "base_keyword": base_kw,
        "generated_query": query,
        "mood": eff_mood,
        "season": eff_season,
        "orientation": eff_orient,
        "available_keywords": all_kw,
        "sample_queries": sample_queries,
        "available_moods": ["any", "dreamy", "peaceful", "cinematic", "moody", "cozy", "dramatic"],
        "available_seasons": ["any", "autumn", "winter", "spring", "summer"],
        "available_orientations": [
            {"id": "vertical_9_16", "name": "Vertical (9:16 Reel)"},
            {"id": "any", "name": "Any Orientation"},
            {"id": "landscape", "name": "Landscape (16:9)"},
        ],
        "available_recency_options": [
            {"id": "any", "name": "Any Time"},
            {"id": "last_12_months", "name": "Last 12 Months"},
            {"id": "last_6_months", "name": "Last 6 Months"},
            {"id": "last_3_months", "name": "Last 3 Months (Fresh)"},
        ],
    }


@app.get("/api/nature/keyword-history")
def get_nature_keyword_history_endpoint(limit: int = Query(50, ge=1, le=100)) -> Dict[str, Any]:
    """Retrieve historical keyword discovery records and yield metrics."""
    pipe = get_nature_pipeline()
    records = pipe.db.get_nature_keyword_history(limit=limit)
    return {"history": records, "total": len(records)}


@app.post("/api/nature/pipeline/run")
def run_nature_pipeline_endpoint(
    req: NatureRunRequest, background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """Trigger the Nature Cinematic Reel pipeline in the background."""
    pipe = get_nature_pipeline()

    def _run_task():
        try:
            pipe.run_pipeline(
                category=req.category,
                keyword=req.keyword,
                mood=req.mood,
                season=req.season,
                recency_preference=req.recency_preference,
                strict_recency=req.strict_recency,
                preferred_orientation=req.preferred_orientation,
                min_quality_score=req.min_quality_score,
                search_limit=req.search_limit,
                excluded_terms=req.excluded_terms,
                max_reels=req.max_reels,
                composition_mode=req.composition_mode,
                template_name=req.template_name,
                custom_thought=req.custom_thought,
                target_duration=req.target_duration,
                font_size=req.font_size,
                line_spacing=req.line_spacing,
                music_path=req.music_path,
                music_volume=req.music_volume,
                source_audio_volume=req.source_audio_volume,
            )
        except Exception as e:
            logger.error(f"Nature pipeline background execution error: {e}")

    background_tasks.add_task(_run_task)
    return {
        "status": "started",
        "category": req.category or "automatic_rotation",
        "keyword": req.keyword or "automatic_rotation",
        "max_reels": req.max_reels,
        "composition_mode": req.composition_mode,
        "template_name": req.template_name or TEMPLATE_MINIMAL_WHITE_SERIF,
    }


@app.post("/api/nature/pipeline/stop")
def stop_nature_pipeline_endpoint() -> Dict[str, Any]:
    """Signal active Nature pipeline run to stop."""
    pipe = get_nature_pipeline()
    pipe.stop()
    return {"status": "stop_requested"}


@app.get("/api/nature/status")
def get_nature_status_endpoint() -> Dict[str, Any]:
    """Get active pipeline job status, progress, and reel counts."""
    pipe = get_nature_pipeline()
    latest_job = pipe.db.get_latest_nature_job()
    pending = pipe.db.get_nature_reels(status=ReelStatus.PENDING.value, limit=1)
    approved = pipe.db.get_nature_reels(status=ReelStatus.APPROVED.value, limit=1)
    rejected = pipe.db.get_nature_reels(status=ReelStatus.REJECTED.value, limit=1)

    return {
        "latest_job": latest_job,
        "counts": {
            "pending_review": len(pipe.db.get_nature_reels(status=ReelStatus.PENDING.value, limit=500)),
            "approved": len(pipe.db.get_nature_reels(status=ReelStatus.APPROVED.value, limit=500)),
            "rejected": len(pipe.db.get_nature_reels(status=ReelStatus.REJECTED.value, limit=500)),
        },
    }


@app.get("/api/nature/media/{file_path:path}")
def serve_nature_media(file_path: str):
    """Safely stream rendered reels and thumbnails to dashboard."""
    base_dir = (Path("downloads")).resolve()
    clean = file_path.lstrip("/\\")

    # Try resolving path directly or relative to downloads/ or downloads/nature/
    candidates = [
        (Path(clean)).resolve(),
        (base_dir / clean).resolve(),
        (base_dir / "nature" / clean).resolve(),
    ]

    resolved_path = None
    for cand in candidates:
        if str(cand).startswith(str(base_dir)) and cand.exists() and cand.is_file():
            resolved_path = cand
            break

    if not resolved_path:
        raise HTTPException(status_code=404, detail="Media file not found")

    content_type = "video/mp4" if resolved_path.suffix.lower() == ".mp4" else "image/jpeg"
    return FileResponse(resolved_path, media_type=content_type)



# ---------------------------------------------------------------------------
# Static Frontend Serving (Vite SPA)
# ---------------------------------------------------------------------------

frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="API route not found")
        target_file = frontend_dist / full_path
        if target_file.is_file():
            return FileResponse(target_file)
        return FileResponse(frontend_dist / "index.html")
