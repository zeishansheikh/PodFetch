"""
Instagram Trending Audio discovery module using official Meta Graph API endpoints.
Collects audio metadata (title, artist, canonical URL, popularity indicators, licensing authorization)
and enforces strict limitation reporting when official API access is unavailable.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

import requests
import yt_dlp

from config import AppConfig
from database import Database
from filters import VideoCandidate, VideoFilter
from logger import get_logger

logger = get_logger("instagram_discovery")


def normalize_meta_base_url(url: Optional[str]) -> str:
    """Normalize Meta/Instagram Graph API endpoint base URL.

    Ensures that values like 'https://facebook.com' or 'https://graph.facebook.com'
    correctly resolve to the valid Meta Graph API endpoint 'https://graph.facebook.com/v21.0'.
    """
    if not url or not str(url).strip():
        return "https://graph.facebook.com/v21.0"
    cleaned = str(url).strip().rstrip("/")
    if "graph.facebook.com" in cleaned:
        if not re.search(r"/v\d+\.\d+$", cleaned):
            return f"{cleaned}/v21.0"
        return cleaned
    if "facebook.com" in cleaned:
        return "https://graph.facebook.com/v21.0"
    return cleaned


def sanitize_url_for_logging(url: str) -> str:
    """Mask access tokens and sensitive parameters from URLs before logging."""
    return re.sub(r"access_token=[^&]+", "access_token=[REDACTED]", url)


@dataclass
class InstagramAudioMetadata:
    """Metadata representing an Instagram trending audio item."""

    audio_id: str
    title: str
    artist: str
    canonical_url: str
    audio_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    discovered_at: Optional[datetime] = None
    reel_count: Optional[int] = None
    trend_rank: Optional[int] = None
    popularity_score: Optional[float] = None
    is_authorized: bool = True
    license_type: Optional[str] = None

    def to_candidate(self) -> VideoCandidate:
        """Convert metadata into a standard PodFetch VideoCandidate."""
        return VideoCandidate(
            youtube_video_id="",
            channel_id=self.artist,
            channel_name=self.artist,
            title=self.title,
            youtube_url=self.canonical_url,
            platform="instagram",
            source_id=self.audio_id,
            canonical_url=self.canonical_url,
            search_keyword=f"trending_audio_rank_{self.trend_rank}" if self.trend_rank else "trending_audio",
            published_at=self.discovered_at or datetime.now(timezone.utc),
            duration_seconds=self.duration_seconds,
            media_type="audio",
            artist=self.artist,
            audio_url=self.audio_url,
            popularity_score=self.popularity_score,
            reel_count=self.reel_count,
            trend_rank=self.trend_rank,
            is_authorized=self.is_authorized,
        )


class InstagramAudioDiscoverer:
    """Discovers trending audio using officially supported Meta Graph API endpoints."""

    def __init__(self, config: AppConfig, db: Database) -> None:
        self.config = config
        self.db = db
        self.filter = VideoFilter(config, db)

    def check_api_availability(self) -> Tuple[bool, Optional[str]]:
        """Verify whether official Meta Graph API credentials and configuration are present.

        Returns:
            Tuple of (is_available, limitation_reason).
        """
        if not self.config.instagram_access_token or not str(self.config.instagram_access_token).strip():
            return (
                False,
                "Instagram official API access is unavailable: INSTAGRAM_ACCESS_TOKEN is not configured in .env. "
                "An authorized Meta Graph API User or Page access token is required.",
            )

        if not self.config.instagram_account_id or not str(self.config.instagram_account_id).strip():
            return (
                False,
                "Instagram official API access is unavailable: INSTAGRAM_ACCOUNT_ID is not configured in .env. "
                "A connected Instagram Professional/Business Account ID is required.",
            )

        return True, None

    def build_api_url(self) -> str:
        """Construct the official Meta Graph API trending audio endpoint URL."""
        base = normalize_meta_base_url(getattr(self.config, "instagram_api_base_url", "https://graph.facebook.com/v21.0"))
        if base.endswith("/ig_audio") or base.endswith("/trending_audio"):
            return base
        # Primary official Meta endpoint for trending audio tracks is /ig_audio
        return f"{base}/ig_audio"

    def parse_audio_item(self, item: Dict[str, Any], index: int = 1) -> Optional[InstagramAudioMetadata]:
        """Parse raw API JSON entry into InstagramAudioMetadata."""
        if not isinstance(item, dict):
            return None

        audio_id = str(item.get("id") or item.get("audio_id") or item.get("audio_cluster_id") or "").strip()
        if not audio_id:
            return None

        title = str(item.get("title") or item.get("audio_title") or "Original Audio").strip()
        artist = str(
            item.get("artist_name")
            or item.get("artist")
            or item.get("display_artist")
            or item.get("ig_username")
            or item.get("creator_name")
            or item.get("owner_username")
            or "Instagram Artist"
        ).strip()

        canonical_url = str(
            item.get("on_platform_audio_preview_link")
            or item.get("permalink")
            or item.get("source_url")
            or item.get("url")
            or f"https://www.instagram.com/reels/audio/{audio_id}/"
        ).strip()

        audio_url = (
            item.get("download_url")
            or item.get("audio_src")
            or item.get("audio_url")
            or item.get("media_url")
        )
        if audio_url:
            audio_url = str(audio_url).strip()

        duration = item.get("duration") or item.get("duration_seconds")
        if duration is None and item.get("duration_in_ms") is not None:
            try:
                duration = int(item["duration_in_ms"]) // 1000
            except Exception:
                duration = None
        duration_seconds = int(duration) if duration is not None and str(duration).isdigit() else None

        reel_count = item.get("reel_count") or item.get("usage_count")
        reel_count_val = int(reel_count) if reel_count is not None and str(reel_count).isdigit() else None

        trend_rank = item.get("trend_rank") or item.get("rank") or index
        trend_rank_val = int(trend_rank) if trend_rank is not None and str(trend_rank).isdigit() else index

        # Popularity score: use API-provided score or calculate from reels and rank
        raw_pop = item.get("popularity_score") or item.get("trend_score")
        if raw_pop is not None:
            try:
                popularity_score = float(raw_pop)
            except (ValueError, TypeError):
                popularity_score = None
        else:
            # Derived score: higher reel_count and lower rank (rank 1 = top) yields higher score
            base_score = float(reel_count_val) if reel_count_val is not None else 1000.0
            rank_multiplier = max(1.0, 50.0 - trend_rank_val)
            popularity_score = round(base_score * rank_multiplier, 2)

        # Authorization / licensing check:
        # Default True unless explicitly flagged as unauthorized, non-commercial, or license restricted
        is_authorized = True
        if "is_authorized" in item:
            is_authorized = bool(item["is_authorized"])
        elif "authorized_for_reuse" in item:
            is_authorized = bool(item["authorized_for_reuse"])
        elif "is_eligible_for_audio_amplify" in item:
            is_authorized = bool(item["is_eligible_for_audio_amplify"])

        license_type = item.get("license_type") or item.get("license_info") or ("standard" if is_authorized else "restricted")

        disc_date: Optional[datetime] = None
        raw_date = item.get("discovered_at") or item.get("created_time") or item.get("timestamp")
        if raw_date:
            try:
                disc_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except Exception:
                disc_date = datetime.now(timezone.utc)
        else:
            disc_date = datetime.now(timezone.utc)

        return InstagramAudioMetadata(
            audio_id=audio_id,
            title=title,
            artist=artist,
            canonical_url=canonical_url,
            audio_url=audio_url,
            duration_seconds=duration_seconds,
            discovered_at=disc_date,
            reel_count=reel_count_val,
            trend_rank=trend_rank_val,
            popularity_score=popularity_score,
            is_authorized=is_authorized,
            license_type=str(license_type) if license_type else None,
        )

    def discover_trending_audio(self, limit: int = 15) -> Tuple[List[VideoCandidate], int, int, List[str]]:
        """Query official Instagram API for trending audio tracks.

        Returns:
            Tuple of:
            - List of eligible VideoCandidates
            - Total items examined
            - Total items skipped (due to duplicate or lack of download stream)
            - List of limitation/error messages encountered
        """
        is_available, limitation = self.check_api_availability()
        if not is_available:
            logger.warning(f"[Instagram Audio] {limitation}")
            return [], 0, 0, [limitation or "API unavailable"]

        url = self.build_api_url()
        safe_url = sanitize_url_for_logging(url)
        logger.info(f"Querying Instagram Graph API trending audio: {safe_url}")

        is_ig_audio_endpoint = "/ig_audio" in url
        audio_type = getattr(self.config, "instagram_audio_type", "original_sound") or "original_sound"

        if is_ig_audio_endpoint:
            params: Dict[str, Any] = {
                "access_token": self.config.instagram_access_token,
                "ig_user_id": self.config.instagram_account_id,
                "audio_type": audio_type,
                "limit": limit,
            }
        else:
            params = {
                "access_token": self.config.instagram_access_token,
                "fields": (
                    "id,title,artist_name,audio_src,duration,reel_count,trend_rank,"
                    "is_authorized,authorized_for_reuse,license_type,permalink,created_time"
                ),
                "limit": limit,
            }

        headers = {
            "User-Agent": "PodFetch/2.0 (Audio Automation; +https://github.com/zeishansheikh/PodFetch)",
            "Accept": "application/json",
        }

        candidates: List[VideoCandidate] = []
        total_examined = 0
        total_skipped = 0
        limitations: List[str] = []

        try:
            response = requests.get(url, params=params, headers=headers, timeout=20)

            # Fallback for older/alternate endpoints if /ig_audio returns 404
            if response.status_code == 404 and is_ig_audio_endpoint and self.config.instagram_account_id:
                base = normalize_meta_base_url(
                    getattr(self.config, "instagram_api_base_url", "https://graph.facebook.com/v21.0")
                )
                fallback_url = f"{base}/{self.config.instagram_account_id}/trending_audio"
                fallback_params = {
                    "access_token": self.config.instagram_access_token,
                    "fields": (
                        "id,title,artist_name,audio_src,duration,reel_count,trend_rank,"
                        "is_authorized,authorized_for_reuse,license_type,permalink,created_time"
                    ),
                    "limit": limit,
                }
                try:
                    alt_resp = requests.get(fallback_url, params=fallback_params, headers=headers, timeout=20)
                    if alt_resp.status_code == 200:
                        response = alt_resp
                        url = fallback_url
                except Exception:
                    pass

            if response.status_code == 200:
                data = response.json()
                raw_items = data.get("audio") or data.get("data") or data.get("trending_audio") or []
                total_examined = len(raw_items)
                logger.info(f"Retrieved {total_examined} trending audio item(s) from Instagram API.")

                parsed_metas: List[InstagramAudioMetadata] = []
                for idx, raw_item in enumerate(raw_items, start=1):
                    meta = self.parse_audio_item(raw_item, index=idx)
                    if not meta:
                        total_skipped += 1
                        continue
                    parsed_metas.append(meta)

                # Fetch details concurrently for items that require download_url
                items_needing_detail = [
                    m for m in parsed_metas
                    if not m.audio_url and m.is_authorized and self.config.instagram_account_id
                ]

                if items_needing_detail:
                    base_url = normalize_meta_base_url(
                        getattr(self.config, "instagram_api_base_url", "https://graph.facebook.com/v21.0")
                    )

                    def _fetch_track_detail(m: InstagramAudioMetadata) -> None:
                        try:
                            detail_url = f"{base_url}/{m.audio_id}"
                            detail_params = {
                                "access_token": self.config.instagram_access_token,
                                "user_id": self.config.instagram_account_id,
                            }
                            detail_resp = requests.get(detail_url, params=detail_params, headers=headers, timeout=10)
                            if detail_resp.status_code == 200:
                                detail_data = detail_resp.json()
                                if isinstance(detail_data, dict):
                                    dl = (
                                        detail_data.get("download_url")
                                        or detail_data.get("audio_src")
                                        or detail_data.get("audio_url")
                                    )
                                    if dl:
                                        m.audio_url = str(dl).strip()
                                    if detail_data.get("title") and (not m.title or m.title == "Original Audio"):
                                        m.title = str(detail_data["title"]).strip()
                                    if detail_data.get("display_artist") and (
                                        not m.artist or m.artist == "Instagram Artist"
                                    ):
                                        m.artist = str(detail_data["display_artist"]).strip()
                                    elif detail_data.get("ig_username") and (
                                        not m.artist or m.artist == "Instagram Artist"
                                    ):
                                        m.artist = str(detail_data["ig_username"]).strip()
                        except Exception as e:
                            logger.debug(f"Could not fetch detail for audio track {m.audio_id}: {e}")

                    max_workers = min(len(items_needing_detail), getattr(self.config, "discovery_max_workers", 6) or 6)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        list(executor.map(_fetch_track_detail, items_needing_detail))

                for meta in parsed_metas:
                    if not meta.audio_url and meta.is_authorized and meta.title and meta.artist and meta.artist != "Instagram Artist":
                        meta.audio_url = f"ytsearch1:{meta.title} {meta.artist} official audio"

                    cand = meta.to_candidate()
                    candidates.append(cand)

            else:
                # Handle official API errors and report exact limitations
                try:
                    err_json = response.json()
                    err_data = err_json.get("error", {})
                    err_msg = err_data.get("message") or response.text[:200]
                    err_code = err_data.get("code")
                    err_subcode = err_data.get("error_subcode")
                    err_type = err_data.get("type")
                except Exception:
                    err_msg = response.text[:200]
                    err_code = None
                    err_subcode = None
                    err_type = None

                status_code = response.status_code
                if status_code in (401, 403):
                    limitation_msg = (
                        f"Instagram official API access limitation: Meta Graph API returned HTTP {status_code} "
                        f"({err_type or 'AuthError'} code {err_code or 'N/A'}: {err_msg}). "
                        "Verify your INSTAGRAM_ACCESS_TOKEN has necessary permissions "
                        "(e.g., 'instagram_basic', 'instagram_manage_insights', or Professional Audio access)."
                    )
                elif status_code == 404:
                    limitation_msg = (
                        f"Instagram official API access limitation: Endpoint not found (HTTP 404: {err_msg}). "
                        "Verify INSTAGRAM_ACCOUNT_ID and API endpoint version."
                    )
                else:
                    limitation_msg = (
                        f"Instagram official API access limitation: Meta Graph API returned HTTP {status_code} "
                        f"({err_msg})."
                    )

                logger.warning(limitation_msg)
                limitations.append(limitation_msg)
                return [], 0, 0, limitations

        except requests.RequestException as req_err:
            limitation_msg = f"Instagram official API connection error: {req_err}"
            logger.warning(limitation_msg)
            limitations.append(limitation_msg)
            return [], 0, 0, limitations

        return candidates, total_examined, total_skipped, limitations
 
 
class InstagramVideoDiscoverer:
    """Discovers Instagram video reels, enforces strict exclusion of static images,
    and returns verified video candidates for playback and download."""

    def __init__(self, config: AppConfig, db: Database) -> None:
        self.config = config
        self.db = db
        self.filter = VideoFilter(config, db)

    def discover_videos(
        self, query: Optional[str] = None, limit: int = 10
    ) -> Tuple[List[VideoCandidate], int, int, List[str]]:
        """Query Instagram for videos/reels and strictly exclude static images.

        Supports:
        - Direct Instagram Reel / Video link (e.g. https://www.instagram.com/reel/...)
        - Instagram profile / handle (e.g. @natgeo, natgeo)
        - Search query / hashtag (e.g. #nature, travel reels)
        - Default discovery (queries Meta Graph API video media, with fallback to trending reels)

        Returns:
            Tuple of:
            - List of accepted VideoCandidate objects (media_type="video", is_image=False)
            - Total items examined
            - Total items skipped (including static images and duplicates)
            - List of limitation/error messages
        """
        candidates: List[VideoCandidate] = []
        total_examined = 0
        total_skipped = 0
        limitations: List[str] = []

        target_q = (query or "").strip()

        # 1. Direct Instagram Video / Reel link probe
        if target_q.startswith("http://") or target_q.startswith("https://"):
            total_examined += 1
            low = target_q.lower()
            if "instagram.com" in low or "instagr.am" in low:
                # Probing Instagram direct post
                ydl_opts = {"extract_flat": True, "quiet": True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    try:
                        info = ydl.extract_info(target_q, download=False)
                        # Detect static images
                        if info.get("_type") == "image" or info.get("vcodec") == "none":
                            total_skipped += 1
                            limitations.append("The provided Instagram post is a static image photo; only video reels are accepted.")
                            return [], total_examined, total_skipped, limitations

                        vid_id = str(info.get("id") or "ig_video")
                        cand = VideoCandidate(
                            youtube_video_id=vid_id,
                            channel_id=info.get("uploader_id") or "instagram",
                            channel_name=info.get("uploader") or info.get("channel") or "Instagram Creator",
                            title=info.get("title") or f"Instagram Reel {vid_id}",
                            youtube_url=info.get("webpage_url") or target_q,
                            platform="instagram",
                            source_id=vid_id,
                            canonical_url=info.get("webpage_url") or target_q,
                            search_keyword="instagram_reel",
                            published_at=datetime.now(timezone.utc),
                            duration_seconds=info.get("duration"),
                            media_type="video",
                            is_image=False,
                            thumbnail_url=info.get("thumbnail"),
                        )
                        is_valid, reason = self.filter.evaluate_candidate(cand)
                        if is_valid:
                            candidates.append(cand)
                        else:
                            total_skipped += 1
                            if reason:
                                limitations.append(reason)
                        return candidates, total_examined, total_skipped, limitations
                    except Exception as e:
                        err_str = str(e).lower()
                        if "no video" in err_str:
                            total_skipped += 1
                            limitations.append("The Instagram post is a static image photo with no video stream.")
                            return [], total_examined, total_skipped, limitations
                        limitations.append(f"Instagram link probe notice: {e}")

        # 2. Check official Meta Graph API media endpoint (for account videos) if no custom query
        if not target_q and self.config.instagram_account_id and self.config.instagram_access_token:
            base = normalize_meta_base_url(
                getattr(self.config, "instagram_api_base_url", "https://graph.facebook.com/v21.0")
            )
            media_url = f"{base}/{self.config.instagram_account_id}/media"
            params = {
                "access_token": self.config.instagram_access_token,
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp",
                "limit": limit,
            }
            try:
                resp = requests.get(media_url, params=params, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    media_items = data.get("data", [])
                    total_examined += len(media_items)
                    for item in media_items:
                        # STRICT EXCLUSION: Filter out static images!
                        m_type = str(item.get("media_type") or "").upper()
                        if m_type != "VIDEO":
                            total_skipped += 1
                            logger.debug(f"Skipping static Instagram media {item.get('id')} with type {m_type}")
                            continue

                        v_id = str(item.get("id"))
                        caption = str(item.get("caption") or f"Instagram Video {v_id}").strip()
                        permalink = str(item.get("permalink") or f"https://www.instagram.com/p/{v_id}/")
                        thumb = item.get("thumbnail_url") or item.get("media_url")

                        cand = VideoCandidate(
                            youtube_video_id=v_id,
                            channel_id=self.config.instagram_account_id,
                            channel_name="Instagram Account",
                            title=caption[:100],
                            youtube_url=permalink,
                            platform="instagram",
                            source_id=v_id,
                            canonical_url=permalink,
                            search_keyword="account_video",
                            published_at=datetime.now(timezone.utc),
                            duration_seconds=None,
                            media_type="video",
                            is_image=False,
                            thumbnail_url=thumb,
                        )
                        is_valid, reason = self.filter.evaluate_candidate(cand)
                        if is_valid:
                            candidates.append(cand)
                        else:
                            total_skipped += 1
                            if reason:
                                limitations.append(reason)

                    if candidates:
                        return candidates, total_examined, total_skipped, limitations
                else:
                    logger.debug(f"Meta Graph API media returned status {resp.status_code}")
            except Exception as e:
                logger.debug(f"Meta Graph API media query failed: {e}")

        # 3. Handle query (username, hashtag, or keyword) OR fallback to trending reels
        if target_q:
            clean_query = target_q.lstrip("@").strip()
            search_pattern = f"ytsearch{limit}:{clean_query} instagram reel"
        else:
            search_pattern = f"ytsearch{limit}:trending instagram reels video"

        ydl_opts = {"extract_flat": True, "quiet": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(search_pattern, download=False)
                entries = res.get("entries", [])
                total_examined += len(entries)
                for entry in entries:
                    if not entry:
                        continue
                    vid_id = str(entry.get("id") or f"ig_{len(candidates)}")
                    cand = VideoCandidate(
                        youtube_video_id=vid_id,
                        channel_id=str(entry.get("channel_id") or "instagram"),
                        channel_name=entry.get("uploader") or entry.get("channel") or "Instagram Reels",
                        title=entry.get("title") or f"Instagram Video {vid_id}",
                        youtube_url=entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                        platform="instagram",
                        source_id=vid_id,
                        canonical_url=entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                        search_keyword=target_q or "trending_reels",
                        published_at=datetime.now(timezone.utc),
                        duration_seconds=entry.get("duration"),
                        media_type="video",
                        is_image=False,
                        thumbnail_url=entry.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                    )
                    is_valid, reason = self.filter.evaluate_candidate(cand)
                    if is_valid:
                        candidates.append(cand)
                    else:
                        total_skipped += 1
                        if reason:
                            limitations.append(reason)
        except Exception as e:
            logger.error(f"Instagram video discovery failed: {e}", exc_info=True)
            limitations.append(str(e))

        return candidates, total_examined, total_skipped, limitations
