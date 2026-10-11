"""
Video filtering logic for identifying eligible full-length podcast videos
and rejecting shorts, livestreams, outdated, or already-processed content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from config import AppConfig
from database import Database, VideoStatus


@dataclass
class VideoCandidate:
    """Represents a discovered video candidate prior to download."""

    youtube_video_id: str
    channel_id: str
    channel_name: str
    title: str
    youtube_url: str
    published_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    is_short: bool = False
    is_live: bool = False
    platform: str = "youtube"
    source_id: Optional[str] = None
    canonical_url: Optional[str] = None
    search_keyword: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None
    is_image: bool = False

    media_type: str = "video"
    artist: Optional[str] = None
    audio_url: Optional[str] = None
    popularity_score: Optional[float] = None
    reel_count: Optional[int] = None
    trend_rank: Optional[int] = None
    is_authorized: bool = True

    def __post_init__(self) -> None:
        if not self.source_id:
            self.source_id = self.youtube_video_id
        if not self.canonical_url:
            self.canonical_url = self.youtube_url
        if not self.youtube_video_id:
            self.youtube_video_id = self.source_id or ""
        if not self.youtube_url:
            self.youtube_url = self.canonical_url or ""

    @property
    def duration_minutes(self) -> float:
        if self.duration_seconds is None:
            return 0.0
        return self.duration_seconds / 60.0

    @property
    def is_vertical(self) -> Optional[bool]:
        """True if vertical aspect ratio (height > width), False if landscape/square, None if unknown."""
        if self.width is not None and self.height is not None and self.width > 0:
            return self.height > self.width
        return None


class VideoFilter:
    """Evaluates candidates against configurable business rules and database state."""

    def __init__(self, config: AppConfig, db: Database) -> None:
        self.config = config
        self.db = db

    def evaluate_candidate(self, candidate: VideoCandidate) -> Tuple[bool, Optional[str]]:
        """Evaluate a single candidate against filter rules.

        Returns:
            Tuple of (is_accepted, rejection_reason).
        """
        # 1. Check SQLite database for prior completion
        lookup_id = candidate.source_id or candidate.youtube_video_id
        if self.db.is_video_processed(lookup_id, platform=candidate.platform):
            return False, "Already processed/uploaded in database"

        existing = self.db.get_video(lookup_id, platform=candidate.platform)
        if existing and existing["status"] in (VideoStatus.DOWNLOADING, VideoStatus.DOWNLOADED):
            return False, f"Video is already currently in progress (status: {existing['status']})"

        # 2. Exclude static images
        if candidate.is_image:
            return False, "Static image pins are excluded; only video media is permitted"

        # 3. Platform-specific filtering: Instagram Trending Audio
        if candidate.platform == "instagram":
            if not candidate.is_authorized:
                return False, "Audio track is not authorized for download or reuse"

            if not candidate.audio_url:
                return False, "No downloadable audio stream URL available"

            if candidate.duration_seconds is not None:
                min_audio = getattr(self.config, "min_audio_duration_seconds", 0)
                max_audio = getattr(self.config, "max_audio_duration_seconds", None)
                if min_audio > 0 and candidate.duration_seconds < min_audio:
                    return (
                        False,
                        f"Duration ({candidate.duration_seconds}s) is less than Instagram minimum "
                        f"required {min_audio}s",
                    )
                if max_audio is not None and candidate.duration_seconds > max_audio:
                    return (
                        False,
                        f"Duration ({candidate.duration_seconds}s) exceeds Instagram maximum "
                        f"limit of {max_audio}s",
                    )

            return True, None

        # 4. Platform-specific filtering: Pinterest
        if candidate.platform == "pinterest":
            # Pinterest duration filter in seconds
            if candidate.duration_seconds is not None:
                if (
                    self.config.min_video_duration_seconds > 0
                    and candidate.duration_seconds < self.config.min_video_duration_seconds
                ):
                    return (
                        False,
                        f"Duration ({candidate.duration_seconds}s) is less than Pinterest minimum "
                        f"required {self.config.min_video_duration_seconds}s",
                    )
                if (
                    self.config.max_video_duration_seconds is not None
                    and candidate.duration_seconds > self.config.max_video_duration_seconds
                ):
                    return (
                        False,
                        f"Duration ({candidate.duration_seconds}s) exceeds Pinterest maximum "
                        f"limit of {self.config.max_video_duration_seconds}s",
                    )

            # Pinterest resolution filter: enforce minimum resolution (e.g. 1080p, 720p)
            if self.config.min_video_resolution and candidate.width and candidate.height:
                is_vert = candidate.height >= candidate.width
                if self.config.min_video_resolution >= 1080:
                    if is_vert:
                        if candidate.width < 1080 and candidate.height < 1920:
                            return (
                                False,
                                f"Resolution ({candidate.width}x{candidate.height}) is lower than required 1080p "
                                f"(requires minimum 1080x1920 vertical or 1920x1080 horizontal)",
                            )
                    else:
                        if candidate.height < 1080 and candidate.width < 1920:
                            return (
                                False,
                                f"Resolution ({candidate.width}x{candidate.height}) is lower than required 1080p "
                                f"(requires minimum 1920x1080)",
                            )
                elif self.config.min_video_resolution >= 720:
                    if is_vert:
                        if candidate.width < 720 and candidate.height < 1280:
                            return (
                                False,
                                f"Resolution ({candidate.width}x{candidate.height}) is lower than required 720p HD",
                            )
                    else:
                        if candidate.height < 720 and candidate.width < 1280:
                            return (
                                False,
                                f"Resolution ({candidate.width}x{candidate.height}) is lower than required 720p HD",
                            )

            return True, None

        # 4. Platform-specific filtering: YouTube
        if candidate.is_short and not self.config.allow_shorts:
            return False, "Shorts are excluded by policy"

        if (
            candidate.duration_seconds is not None
            and candidate.duration_seconds <= 60
            and not self.config.allow_shorts
        ):
            return False, f"Video length ({candidate.duration_seconds}s) matches YouTube Short criteria"

        if candidate.is_live and not self.config.allow_livestreams:
            return False, "Livestreams / ongoing premieres are excluded"

        # Check minimum duration for YouTube podcasts
        min_seconds = self.config.min_duration_minutes * 60
        if candidate.duration_seconds is not None and candidate.duration_seconds < min_seconds:
            return (
                False,
                f"Duration ({candidate.duration_seconds // 60}m {candidate.duration_seconds % 60}s) "
                f"is less than minimum required {self.config.min_duration_minutes}m",
            )

        # Check maximum duration for YouTube
        if self.config.max_duration_minutes is not None and candidate.duration_seconds is not None:
            max_seconds = self.config.max_duration_minutes * 60
            if candidate.duration_seconds > max_seconds:
                return (
                    False,
                    f"Duration ({candidate.duration_seconds // 60}m) exceeds maximum limit "
                    f"of {self.config.max_duration_minutes}m",
                )

        # Check video age for YouTube
        if candidate.published_at is not None:
            now = datetime.now(timezone.utc)
            pub = candidate.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)

            age_days = (now - pub).total_seconds() / (24 * 3600)
            if age_days > self.config.max_video_age_days:
                return (
                    False,
                    f"Video was published {age_days:.1f} days ago, exceeding {self.config.max_video_age_days} days limit",
                )

        return True, None

    def filter_candidates(
        self, candidates: List[VideoCandidate]
    ) -> Tuple[List[VideoCandidate], List[Tuple[VideoCandidate, str]]]:
        """Filter a list of candidates into accepted and rejected collections."""
        accepted: List[VideoCandidate] = []
        rejected: List[Tuple[VideoCandidate, str]] = []

        for candidate in candidates:
            is_valid, reason = self.evaluate_candidate(candidate)
            if is_valid:
                accepted.append(candidate)
            else:
                rejected.append((candidate, reason or "Filtered out"))

        return accepted, rejected
