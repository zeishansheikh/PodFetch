"""
Channel discovery and video selection module.
Discovers recent uploads from YouTube channels, resolves handles,
and fairly distributes selections across configured channels.
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yt_dlp

from config import AppConfig
from database import Database, VideoStatus
from filters import VideoCandidate, VideoFilter
from logger import get_logger

logger = get_logger("discovery")


def normalize_channel_url(channel_input: str) -> str:
    """Normalize various channel identifier formats into a standard YouTube channel URL."""
    cleaned = channel_input.strip()

    if not cleaned:
        raise ValueError("Empty channel identifier provided")

    # Already full URL
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        # If it's a channel or handle URL without a subtab, ensure we target /videos
        url_without_slash = cleaned.rstrip("/")
        if (
            "/@" in url_without_slash
            or "/channel/" in url_without_slash
            or "/c/" in url_without_slash
            or "/user/" in url_without_slash
        ):
            if not any(
                url_without_slash.endswith(tab)
                for tab in ("/videos", "/shorts", "/streams", "/podcasts", "/featured")
            ):
                return f"{url_without_slash}/videos"
        return cleaned

    # Handle format: @handle
    if cleaned.startswith("@"):
        return f"https://www.youtube.com/{cleaned}/videos"

    # Channel ID format: UC... (24 characters)
    if cleaned.startswith("UC") and len(cleaned) == 24:
        return f"https://www.youtube.com/channel/{cleaned}/videos"

    # Fallback default assuming handle or username
    return f"https://www.youtube.com/@{cleaned}/videos"


class ChannelDiscoverer:
    """Discovers recent videos from YouTube channels using yt-dlp."""

    def __init__(self, config: AppConfig, db: Database) -> None:
        self.config = config
        self.db = db
        self.filter = VideoFilter(config, db)

    def discover_channel_videos(
        self,
        channel_url: str,
        max_probe: int = 15,
    ) -> List[VideoCandidate]:
        """Probe the channel's latest uploads tab and return parsed candidate objects."""
        target_url = normalize_channel_url(channel_url)
        logger.info(f"Checking YouTube channel: {target_url}")

        ydl_opts: Dict[str, Any] = {
            "extract_flat": True,
            "playlistend": max_probe,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "socket_timeout": 15,
        }

        candidates: List[VideoCandidate] = []

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)

            if not info:
                logger.warning(f"No metadata returned for channel: {channel_url}")
                return []

            canonical_channel_id = (
                info.get("channel_id") or info.get("id") or channel_url
            )
            canonical_channel_name = (
                info.get("channel") or info.get("uploader") or info.get("title") or "YouTube Channel"
            )

            entries = info.get("entries") or []
            logger.info(f"Fetched {len(entries)} recent entries from '{canonical_channel_name}'")

            for entry in entries:
                if not entry or not isinstance(entry, dict):
                    continue

                video_id = entry.get("id")
                if not video_id:
                    continue

                video_title = entry.get("title") or "Untitled Video"
                video_url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
                if not video_url.startswith("http"):
                    video_url = f"https://www.youtube.com/watch?v={video_id}"

                # Parse duration
                duration = entry.get("duration")

                # Parse timestamp / published_at
                published_at: Optional[datetime] = None
                timestamp = entry.get("timestamp")
                if timestamp:
                    try:
                        published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    except Exception:
                        pass
                elif entry.get("upload_date"):
                    try:
                        published_at = datetime.strptime(
                            str(entry["upload_date"]), "%Y%m%d"
                        ).replace(tzinfo=timezone.utc)
                    except Exception:
                        pass

                is_live = bool(
                    entry.get("is_live")
                    or entry.get("live_status") in ("is_live", "is_upcoming", "post_live")
                )
                is_short = "/shorts/" in video_url or bool(entry.get("is_short"))

                # If duration or key properties are missing in flat extraction, fetch full video metadata
                if duration is None:
                    try:
                        detail_opts = {
                            "quiet": True,
                            "no_warnings": True,
                            "skip_download": True,
                            "ignoreerrors": True,
                            "socket_timeout": 10,
                        }
                        with yt_dlp.YoutubeDL(detail_opts) as detail_ydl:
                            detail = detail_ydl.extract_info(video_url, download=False)
                            if detail:
                                duration = detail.get("duration")
                                if not published_at and detail.get("timestamp"):
                                    published_at = datetime.fromtimestamp(
                                        detail["timestamp"], tz=timezone.utc
                                    )
                                is_live = is_live or bool(detail.get("is_live"))
                    except Exception as ex:
                        logger.debug(f"Failed to fetch detailed info for {video_id}: {ex}")

                candidate = VideoCandidate(
                    youtube_video_id=video_id,
                    channel_id=canonical_channel_id,
                    channel_name=canonical_channel_name,
                    title=video_title,
                    youtube_url=video_url,
                    published_at=published_at,
                    duration_seconds=int(duration) if duration is not None else None,
                    is_short=is_short,
                    is_live=is_live,
                )
                candidates.append(candidate)

        except Exception as e:
            logger.error(f"Error querying channel {channel_url}: {e}", exc_info=True)

        return candidates

    def collect_and_filter_all_channels(
        self,
        channels: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, List[VideoCandidate]], int, int]:
        """Query all configured channels, filter videos, and register discovered items.

        Returns:
            Tuple of:
            - Dict mapping channel_id -> list of eligible VideoCandidates
            - Total candidates examined
            - Total candidates skipped
        """
        target_channels = channels or self.config.youtube_channels
        eligible_by_channel: Dict[str, List[VideoCandidate]] = defaultdict(list)
        total_examined = 0
        total_skipped = 0

        for ch in target_channels:
            candidates = self.discover_channel_videos(ch)
            total_examined += len(candidates)

            accepted, rejected = self.filter.filter_candidates(candidates)
            total_skipped += len(rejected)

            for cand, reason in rejected:
                logger.info(f"Skipped '{cand.title}' ({cand.youtube_video_id}): {reason}")
                # Record rejected items in database as SKIPPED so future runs quickly skip them
                if not self.config.dry_run and not self.db.is_video_processed(cand.youtube_video_id):
                    self.db.upsert_video(
                        youtube_video_id=cand.youtube_video_id,
                        title=cand.title,
                        youtube_url=cand.youtube_url,
                        channel_id=cand.channel_id,
                        channel_name=cand.channel_name,
                        published_at=cand.published_at.isoformat() if cand.published_at else None,
                        duration=cand.duration_seconds,
                        status=VideoStatus.SKIPPED,
                        error_message=f"Filter: {reason}",
                    )

            for cand in accepted:
                eligible_by_channel[cand.channel_id].append(cand)
                # Register eligible candidate as DISCOVERED in DB
                if not self.config.dry_run:
                    self.db.upsert_video(
                        youtube_video_id=cand.youtube_video_id,
                        title=cand.title,
                        youtube_url=cand.youtube_url,
                        channel_id=cand.channel_id,
                        channel_name=cand.channel_name,
                        published_at=cand.published_at.isoformat() if cand.published_at else None,
                        duration=cand.duration_seconds,
                        status=VideoStatus.DISCOVERED,
                    )

        return eligible_by_channel, total_examined, total_skipped


def select_videos_for_run(
    eligible_by_channel: Dict[str, List[VideoCandidate]],
    min_count: int,
    max_count: int,
    historical_counts: Dict[str, int],
    exact_limit: Optional[int] = None,
) -> List[VideoCandidate]:
    """Select videos fairly across channels using a randomized, balanced round-robin strategy.

    Args:
        eligible_by_channel: Dict of channel_id -> eligible VideoCandidate list.
        min_count: Minimum videos to select.
        max_count: Maximum videos to select.
        historical_counts: Past selection counts by channel_id from database.
        exact_limit: Optional CLI override forcing an exact selection count.

    Returns:
        List of selected VideoCandidate objects.
    """
    all_eligible: List[VideoCandidate] = []
    for cands in eligible_by_channel.values():
        all_eligible.extend(cands)

    if not all_eligible:
        return []

    # Determine how many videos to select
    if exact_limit is not None and exact_limit > 0:
        target_count = min(exact_limit, len(all_eligible))
    else:
        target_count = random.randint(min_count, max_count)
        target_count = min(target_count, len(all_eligible))

    if target_count <= 0:
        return []

    # Sort available candidates in each channel so newest uploads come first
    candidates_pool: Dict[str, List[VideoCandidate]] = {}
    for ch_id, cands in eligible_by_channel.items():
        if cands:
            sorted_cands = sorted(
                cands,
                key=lambda x: x.published_at.timestamp() if x.published_at else 0,
                reverse=True,
            )
            candidates_pool[ch_id] = list(sorted_cands)

    # Order channels by least historically selected to distribute fairly over time
    channels = list(candidates_pool.keys())
    # Shuffle first to randomize ties
    random.shuffle(channels)
    # Stable sort by historical upload count
    channels.sort(key=lambda ch: historical_counts.get(ch, 0))

    selected: List[VideoCandidate] = []

    # Round-robin distribution
    while len(selected) < target_count and any(candidates_pool.values()):
        for ch in channels:
            if len(selected) >= target_count:
                break
            if candidates_pool.get(ch):
                chosen_candidate = candidates_pool[ch].pop(0)
                selected.append(chosen_candidate)

    return selected
