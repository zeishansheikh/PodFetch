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
from instagram_discovery import InstagramAudioDiscoverer
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


class VideoDownloadPayload(BaseModel):
    url: str
    platform: str = "youtube"
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
    audio_type: Optional[str] = Query(None, description="'music' or 'original_sound'"),
    limit: int = Query(15, ge=1, le=30),
) -> Dict[str, Any]:
    """Discover trending audio tracks from official Instagram Graph API."""
    config = get_config()
    if audio_type:
        config.instagram_audio_type = audio_type

    db = get_db(config)
    discoverer = InstagramAudioDiscoverer(config, db)
    is_available, error_msg = discoverer.check_api_availability()

    if not is_available:
        return {
            "available": False,
            "reason": error_msg or "Instagram API access is unconfigured or unauthorized",
            "account_id": config.instagram_account_id,
            "audio_type": config.instagram_audio_type,
            "total_found": 0,
            "items": [],
            "limitations": [error_msg] if error_msg else [],
        }

    try:
        candidates, examined, skipped, limitations = discoverer.discover_trending_audio(limit=limit)
        items: List[Dict[str, Any]] = []
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
            })

        return {
            "available": True,
            "account_id": config.instagram_account_id,
            "audio_type": config.instagram_audio_type,
            "total_examined": examined,
            "total_skipped": skipped,
            "total_found": len(items),
            "items": items,
            "limitations": limitations,
        }
    except Exception as e:
        logger.error(f"Instagram audio discovery failed: {e}", exc_info=True)
        return {
            "available": False,
            "reason": f"Instagram discovery failed: {e}",
            "account_id": config.instagram_account_id,
            "audio_type": config.instagram_audio_type,
            "total_found": 0,
            "items": [],
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
        if req.platform == "instagram":
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
                    file_path=str(audio_path),
                    drive_file_id=drive_file_id,
                    duration=cand.duration_seconds,
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

        elif req.platform == "youtube":
            y_downloader = VideoDownloader(config)
            vid_path = y_downloader.download_video(cand)
            downloaded_at = datetime.now(timezone.utc).isoformat()
            db.update_status(
                source_id=cand.source_id,
                platform="youtube",
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
                        platform="youtube",
                        keyword_or_channel=cand.channel_name or "youtube",
                        source_id=cand.source_id,
                        extension="mp4",
                    )
                    drive_file_id, drive_path = drive_uploader.upload_video(
                        vid_path, custom_filename=clean_filename, platform="youtube"
                    )
                except Exception as upload_err:
                    logger.error(f"Google Drive upload failed for YouTube video {cand.title}: {upload_err}", exc_info=True)

            if drive_file_id:
                uploaded_at = datetime.now(timezone.utc).isoformat()
                db.update_status(
                    source_id=cand.source_id,
                    platform="youtube",
                    status=VideoStatus.UPLOADED,
                    drive_file_id=drive_file_id,
                    drive_path=drive_path,
                    uploaded_at=uploaded_at,
                )

            return {
                "success": True,
                "status": "UPLOADED" if drive_file_id else "DOWNLOADED",
                "message": f"Successfully processed YouTube video '{req.title}'" + (f" and uploaded to Google Drive ({drive_file_id})" if drive_file_id else ""),
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
        if any(d in low for d in ("youtube.com", "youtu.be", "pinterest.com", "pin.it")) or target_str.startswith("www."):
            target_str = f"https://{target_str}"
            low = target_str.lower()

    # Determine platform
    if "pinterest.com" in low or "pin.it" in low:
        effective_platform = "pinterest"
    elif "youtube.com" in low or "youtu.be" in low:
        effective_platform = "youtube"
    else:
        effective_platform = platform_hint.lower() if platform_hint else "youtube"

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
    res = discover_instagram(audio_type=payload.audio_type, limit=payload.limit)
    return {
        "status": "error" if not res.get("available") and "reason" in res else "ok",
        "message": res.get("reason"),
        "tracks": res.get("items", []),
        "total_found": res.get("total_found", 0),
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
