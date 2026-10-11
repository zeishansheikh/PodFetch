"""
Instagram Trending Audio discovery module using official Meta Graph API endpoints.
Collects audio metadata (title, artist, canonical URL, popularity indicators, licensing authorization)
and enforces strict limitation reporting when official API access is unavailable.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import AppConfig
from database import Database
from filters import VideoCandidate, VideoFilter
from logger import get_logger

logger = get_logger("instagram_discovery")


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
        base = getattr(self.config, "instagram_api_base_url", "https://graph.facebook.com/v21.0").rstrip("/")
        account_id = self.config.instagram_account_id
        # Primary official endpoint: /{ig_account_id}/trending_audio
        return f"{base}/{account_id}/trending_audio"

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
            or item.get("creator_name")
            or item.get("owner_username")
            or "Instagram Artist"
        ).strip()

        canonical_url = str(
            item.get("permalink")
            or item.get("source_url")
            or item.get("url")
            or f"https://www.instagram.com/reels/audio/{audio_id}/"
        ).strip()

        audio_url = item.get("audio_src") or item.get("audio_url") or item.get("download_url") or item.get("media_url")
        if audio_url:
            audio_url = str(audio_url).strip()

        duration = item.get("duration") or item.get("duration_seconds")
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
            if response.status_code == 200:
                data = response.json()
                raw_items = data.get("data") or data.get("trending_audio") or []
                total_examined = len(raw_items)
                logger.info(f"Retrieved {total_examined} trending audio item(s) from Instagram API.")

                for idx, raw_item in enumerate(raw_items, start=1):
                    meta = self.parse_audio_item(raw_item, index=idx)
                    if not meta:
                        total_skipped += 1
                        continue

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
