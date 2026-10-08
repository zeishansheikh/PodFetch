"""
Configuration management and environment variable loader.
Validates settings and ensures safe defaults for unattended cloud execution.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv


def _parse_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "y", "on")


def _extract_multiline_channels_from_file(env_file_path: Path) -> List[str]:
    """Extract multiline YOUTUBE_CHANNELS bracketed array directly from .env file if present."""
    if not env_file_path.exists():
        return []
    try:
        content = env_file_path.read_text(encoding="utf-8")
        match = re.search(r"YOUTUBE_CHANNELS\s*=\s*(\[.*?\])", content, re.DOTALL)
        if match:
            raw_block = match.group(1)
            # Remove trailing commas before closing bracket for valid JSON
            cleaned_json = re.sub(r",\s*\]", "]", raw_block)
            try:
                parsed = json.loads(cleaned_json)
                if isinstance(parsed, list):
                    return [str(c).strip() for c in parsed if str(c).strip()]
            except json.JSONDecodeError:
                pass

            # Fallback: regex search for all quoted strings inside the bracketed block
            matches = re.findall(r"[\"']([^\"']+)[\"']", raw_block)
            return [m.strip() for m in matches if m.strip()]
    except Exception:
        pass
    return []


def _parse_channels(raw_val: Optional[str], env_file: Optional[Path] = None) -> List[str]:
    """Parse channel list from JSON array string, comma-delimited string, or multiline file."""
    # If raw_val was truncated by standard dotenv parser (e.g. just '['), attempt reading from file
    if env_file and (not raw_val or raw_val.strip() in ("[", "[]")):
        file_channels = _extract_multiline_channels_from_file(env_file)
        if file_channels:
            return file_channels

    if not raw_val:
        return []

    stripped = raw_val.strip()

    # Avoid treating isolated bracket as a channel
    if stripped in ("[", "]", "[]"):
        if env_file:
            return _extract_multiline_channels_from_file(env_file)
        return []

    # Attempt JSON array parsing first
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            cleaned_json = re.sub(r",\s*\]", "]", stripped)
            parsed = json.loads(cleaned_json)
            if isinstance(parsed, list):
                return [str(c).strip() for c in parsed if str(c).strip()]
        except json.JSONDecodeError:
            pass
        # Fallback regex for bracketed quoted strings
        matches = re.findall(r"[\"']([^\"']+)[\"']", stripped)
        if matches:
            return [m.strip() for m in matches if m.strip()]

    # Split by comma or newline
    channels: List[str] = []
    lines = stripped.replace("\r", "\n").split("\n")
    for line in lines:
        for chunk in line.split(","):
            cleaned = chunk.strip(" '\"[]")
            if cleaned and not cleaned.startswith("#") and cleaned not in ("[", "]"):
                channels.append(cleaned)
    return channels


@dataclass
class AppConfig:
    """Strongly typed application configuration."""

    youtube_channels: List[str] = field(default_factory=list)
    min_videos_per_run: int = 1
    max_videos_per_run: int = 3
    google_drive_folder_id: str = ""

    max_video_age_days: int = 30
    min_duration_minutes: int = 20
    max_duration_minutes: Optional[int] = None
    allow_shorts: bool = False
    allow_livestreams: bool = False

    use_date_subfolders: bool = True
    dry_run: bool = False

    database_path: Path = field(default_factory=lambda: Path("downloads.db"))
    log_dir: Path = field(default_factory=lambda: Path("logs"))
    temp_dir: Path = field(default_factory=lambda: Path("temp"))

    download_quality: str = "1080p"
    max_retries: int = 3
    backoff_factor: float = 2.0

    # Google Auth Settings
    google_service_account_file: Optional[str] = None
    google_service_account_json: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_refresh_token: Optional[str] = None
    google_token_file: Optional[str] = None

    def validate(self, is_status_command: bool = False) -> None:
        """Validate critical configuration fields and raise informative errors."""
        if is_status_command:
            # Viewing status doesn't require Google Drive credentials or channel list
            return

        if self.min_videos_per_run < 1:
            raise ValueError(f"MIN_VIDEOS_PER_RUN must be >= 1, got {self.min_videos_per_run}")

        if self.max_videos_per_run < self.min_videos_per_run:
            raise ValueError(
                f"MAX_VIDEOS_PER_RUN ({self.max_videos_per_run}) cannot be less than "
                f"MIN_VIDEOS_PER_RUN ({self.min_videos_per_run})"
            )

        if self.min_duration_minutes < 0:
            raise ValueError("MIN_DURATION_MINUTES cannot be negative")

        if self.max_video_age_days < 1:
            raise ValueError("MAX_VIDEO_AGE_DAYS must be >= 1")

        if not self.youtube_channels:
            raise ValueError(
                "No YouTube channels configured! Set YOUTUBE_CHANNELS in your .env file or pass --channel."
            )

        # In live (non-dry-run) mode, check Google Drive settings
        if not self.dry_run:
            if not self.google_drive_folder_id:
                raise ValueError(
                    "GOOGLE_DRIVE_FOLDER_ID is required for uploading to Google Drive. "
                    "Set it in .env or use --dry-run for testing."
                )

            has_service_account = bool(
                (self.google_service_account_file and Path(self.google_service_account_file).exists())
                or self.google_service_account_json
            )
            has_oauth_refresh = bool(
                self.google_client_id and self.google_client_secret and self.google_refresh_token
            )
            token_path = Path(self.google_token_file) if self.google_token_file else Path("token.json")
            has_token_file = token_path.exists()

            if not (has_service_account or has_oauth_refresh or has_token_file):
                raise ValueError(
                    "Missing Google Drive authentication credentials. Provide either:\n"
                    "  1. GOOGLE_SERVICE_ACCOUNT_FILE (path to service account JSON)\n"
                    "  2. GOOGLE_SERVICE_ACCOUNT_JSON (raw JSON string in env var)\n"
                    "  3. GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN\n"
                    "  4. GOOGLE_TOKEN_FILE (path to saved credentials JSON)\n"
                    "Tip: Run with --dry-run to test channel discovery without credentials."
                )


def load_config(env_file: Optional[str] = None) -> AppConfig:
    """Load configuration from .env file and environment variables."""
    target_env = Path(env_file) if env_file else Path(".env")
    if target_env.exists():
        load_dotenv(dotenv_path=target_env, override=True)
    else:
        load_dotenv(override=False)

    channels = _parse_channels(os.getenv("YOUTUBE_CHANNELS", ""), env_file=target_env)

    max_dur = os.getenv("MAX_DURATION_MINUTES")
    max_duration_minutes = int(max_dur) if max_dur and max_dur.strip().isdigit() else None

    return AppConfig(
        youtube_channels=channels,
        min_videos_per_run=int(os.getenv("MIN_VIDEOS_PER_RUN", "1")),
        max_videos_per_run=int(os.getenv("MAX_VIDEOS_PER_RUN", "3")),
        google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip(),
        max_video_age_days=int(os.getenv("MAX_VIDEO_AGE_DAYS", "30")),
        min_duration_minutes=int(os.getenv("MIN_DURATION_MINUTES", "20")),
        max_duration_minutes=max_duration_minutes,
        allow_shorts=_parse_bool(os.getenv("ALLOW_SHORTS", "false")),
        allow_livestreams=_parse_bool(os.getenv("ALLOW_LIVESTREAMS", "false")),
        use_date_subfolders=_parse_bool(os.getenv("USE_DATE_SUBFOLDERS", "true")),
        dry_run=_parse_bool(os.getenv("DRY_RUN", "false")),
        database_path=Path(os.getenv("DATABASE_PATH", "downloads.db")),
        log_dir=Path(os.getenv("LOG_DIR", "logs")),
        temp_dir=Path(os.getenv("TEMP_DIR", "temp")),
        download_quality=os.getenv("DOWNLOAD_QUALITY", "1080p").strip(),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        backoff_factor=float(os.getenv("BACKOFF_FACTOR", "2.0")),
        google_service_account_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        google_refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        google_token_file=os.getenv("GOOGLE_TOKEN_FILE"),
    )
