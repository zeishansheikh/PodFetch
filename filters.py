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

    @property
    def duration_minutes(self) -> float:
        if self.duration_seconds is None:
            return 0.0
        return self.duration_seconds / 60.0


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
        if self.db.is_video_processed(candidate.youtube_video_id):
            return False, "Already processed/uploaded in database"

        existing = self.db.get_video(candidate.youtube_video_id)
        if existing and existing["status"] in (VideoStatus.DOWNLOADING, VideoStatus.DOWNLOADED):
            return False, f"Video is already currently in progress (status: {existing['status']})"

        # 2. Check Shorts
        if candidate.is_short and not self.config.allow_shorts:
            return False, "Shorts are excluded by policy"

        if (
            candidate.duration_seconds is not None
            and candidate.duration_seconds <= 60
            and not self.config.allow_shorts
        ):
            return False, f"Video length ({candidate.duration_seconds}s) matches YouTube Short criteria"

        # 3. Check Livestreams
        if candidate.is_live and not self.config.allow_livestreams:
            return False, "Livestreams / ongoing premieres are excluded"

        # 4. Check minimum duration
        min_seconds = self.config.min_duration_minutes * 60
        if candidate.duration_seconds is not None and candidate.duration_seconds < min_seconds:
            return (
                False,
                f"Duration ({candidate.duration_seconds // 60}m {candidate.duration_seconds % 60}s) "
                f"is less than minimum required {self.config.min_duration_minutes}m",
            )

        # 5. Check maximum duration (if configured)
        if self.config.max_duration_minutes is not None and candidate.duration_seconds is not None:
            max_seconds = self.config.max_duration_minutes * 60
            if candidate.duration_seconds > max_seconds:
                return (
                    False,
                    f"Duration ({candidate.duration_seconds // 60}m) exceeds maximum limit "
                    f"of {self.config.max_duration_minutes}m",
                )

        # 6. Check video age
        if candidate.published_at is not None:
            now = datetime.now(timezone.utc)
            # Ensure published_at is timezone-aware
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
