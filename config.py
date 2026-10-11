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


DEFAULT_PINTEREST_KEYWORDS: List[str] = [
    "aesthetic nature videos",
    "nature aesthetic 4k",
    "dreamy nature aesthetic",
    "cinematic nature scenery",
    "peaceful nature clips",
    "aesthetic sunset nature",
    "pink sunset aesthetic",
    "golden hour nature",
    "mountain sunset aesthetic",
    "blue sky clouds aesthetic",
    "river flowing nature aesthetic",
    "waterfall aesthetic video",
    "ocean waves aesthetic",
    "forest road aesthetic",
    "flowers field aesthetic",
    "wildflowers nature aesthetic",
    "moon night aesthetic nature",
    "misty mountains aesthetic",
    "lake mountain scenery",
    "autumn nature aesthetic",
    "winter night nature aesthetic",
    "nature b roll vertical",
    "nature aesthetic video 9:16",
    "relaxing nature scenery video",
    "moody nature aesthetic",
]


def _extract_multiline_keywords_from_file(env_file_path: Path) -> List[str]:
    """Extract multiline PINTEREST_KEYWORDS bracketed array directly from .env file if present."""
    if not env_file_path.exists():
        return []
    try:
        content = env_file_path.read_text(encoding="utf-8")
        match = re.search(r"PINTEREST_KEYWORDS\s*=\s*(\[.*?\])", content, re.DOTALL)
        if match:
            raw_block = match.group(1)
            cleaned_json = re.sub(r",\s*\]", "]", raw_block)
            try:
                parsed = json.loads(cleaned_json)
                if isinstance(parsed, list):
                    return [str(c).strip() for c in parsed if str(c).strip()]
            except json.JSONDecodeError:
                pass
            matches = re.findall(r"[\"']([^\"']+)[\"']", raw_block)
            return [m.strip() for m in matches if m.strip()]
    except Exception:
        pass
    return []


def _parse_keywords(
    raw_val: Optional[str],
    keywords_file: Optional[Path] = None,
    env_file: Optional[Path] = None,
) -> List[str]:
    """Parse keywords from dedicated file, env var (JSON array or comma-delimited), or default list."""
    # 1. Dedicated keywords text file if present and readable
    if keywords_file and keywords_file.exists():
        try:
            lines = keywords_file.read_text(encoding="utf-8").splitlines()
            cleaned = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
            if cleaned:
                return cleaned
        except Exception:
            pass

    # 2. Check multiline bracket block in env_file
    if env_file and (not raw_val or raw_val.strip() in ("[", "[]")):
        file_keywords = _extract_multiline_keywords_from_file(env_file)
        if file_keywords:
            return file_keywords

    if not raw_val:
        return list(DEFAULT_PINTEREST_KEYWORDS)

    stripped = raw_val.strip()
    if stripped in ("[", "]", "[]"):
        if env_file:
            extracted = _extract_multiline_keywords_from_file(env_file)
            if extracted:
                return extracted
        return list(DEFAULT_PINTEREST_KEYWORDS)

    # JSON array parsing
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            cleaned_json = re.sub(r",\s*\]", "]", stripped)
            parsed = json.loads(cleaned_json)
            if isinstance(parsed, list):
                res = [str(c).strip() for c in parsed if str(c).strip()]
                if res:
                    return res
        except json.JSONDecodeError:
            pass
        matches = re.findall(r"[\"']([^\"']+)[\"']", stripped)
        if matches:
            return [m.strip() for m in matches if m.strip()]

    # Split by comma or newline
    keywords: List[str] = []
    lines = stripped.replace("\r", "\n").split("\n")
    for line in lines:
        for chunk in line.split(","):
            cleaned = chunk.strip(" '\"[]")
            if cleaned and not cleaned.startswith("#") and cleaned not in ("[", "]"):
                keywords.append(cleaned)
    return keywords if keywords else list(DEFAULT_PINTEREST_KEYWORDS)


def _parse_sources(
    raw_val: Optional[str],
    youtube_enabled: bool,
    pinterest_enabled: bool,
    instagram_enabled: bool = True,
) -> List[str]:
    """Determine enabled sources from ENABLED_SOURCES string and boolean flags."""
    sources: List[str] = []
    if raw_val:
        for s in raw_val.split(","):
            cleaned = s.strip().lower()
            if cleaned in ("youtube", "pinterest", "instagram") and cleaned not in sources:
                sources.append(cleaned)

    # If ENABLED_SOURCES wasn't set, build from individual flags
    if not sources:
        if youtube_enabled:
            sources.append("youtube")
        if pinterest_enabled:
            sources.append("pinterest")
        if instagram_enabled:
            sources.append("instagram")

    # Filter out sources explicitly disabled via individual flags
    final_sources: List[str] = []
    for s in sources:
        if s == "youtube" and not youtube_enabled:
            continue
        if s == "pinterest" and not pinterest_enabled:
            continue
        if s == "instagram" and not instagram_enabled:
            continue
        final_sources.append(s)

    return final_sources


DEFAULT_INSTAGRAM_ACCOUNT_ID: str = "17841435006386072"


@dataclass
class AppConfig:
    """Strongly typed application configuration."""

    # Sources & Discovery Settings
    enabled_sources: List[str] = field(default_factory=lambda: ["youtube", "pinterest", "instagram"])
    pinterest_enabled: bool = True
    youtube_enabled: bool = True
    instagram_enabled: bool = True
    prefer_vertical: bool = True
    min_video_duration_seconds: int = 10
    max_video_duration_seconds: int = 30
    min_video_resolution: int = 1080

    # Instagram Specific
    instagram_access_token: Optional[str] = None
    instagram_account_id: Optional[str] = DEFAULT_INSTAGRAM_ACCOUNT_ID
    instagram_api_base_url: str = "https://graph.facebook.com/v21.0"
    instagram_audio_manifest_path: Path = field(default_factory=lambda: Path("audio_manifest.json"))
    instagram_audio_type: str = "original_sound"
    min_audio_duration_seconds: int = 5
    max_audio_duration_seconds: Optional[int] = 90

    # Pinterest Specific
    pinterest_keywords: List[str] = field(default_factory=lambda: list(DEFAULT_PINTEREST_KEYWORDS))
    pinterest_keywords_file: Optional[str] = None
    pinterest_access_token: Optional[str] = None
    pinterest_session_cookie: Optional[str] = None

    # YouTube Specific
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
    concurrent_fragment_downloads: int = 8
    discovery_max_workers: int = 6
    discovery_candidate_pool: int = 30

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
            # Viewing status doesn't require credentials or channel/keyword lists
            return

        if self.min_videos_per_run < 1:
            raise ValueError(f"MIN_VIDEOS_PER_RUN must be >= 1, got {self.min_videos_per_run}")

        if self.max_videos_per_run < self.min_videos_per_run:
            raise ValueError(
                f"MAX_VIDEOS_PER_RUN ({self.max_videos_per_run}) cannot be less than "
                f"MIN_VIDEOS_PER_RUN ({self.min_videos_per_run})"
            )

        if self.min_video_duration_seconds < 0:
            raise ValueError("MIN_VIDEO_DURATION_SECONDS cannot be negative")

        if (
            self.max_video_duration_seconds is not None
            and self.max_video_duration_seconds < self.min_video_duration_seconds
        ):
            raise ValueError(
                f"MAX_VIDEO_DURATION_SECONDS ({self.max_video_duration_seconds}) cannot be less than "
                f"MIN_VIDEO_DURATION_SECONDS ({self.min_video_duration_seconds})"
            )

        if self.min_duration_minutes < 0:
            raise ValueError("MIN_DURATION_MINUTES cannot be negative")

        if self.max_video_age_days < 1:
            raise ValueError("MAX_VIDEO_AGE_DAYS must be >= 1")

        if not self.enabled_sources:
            raise ValueError(
                "No sources enabled! Check ENABLED_SOURCES, YOUTUBE_ENABLED, PINTEREST_ENABLED, and INSTAGRAM_ENABLED."
            )

        if "youtube" in self.enabled_sources and not self.youtube_channels:
            raise ValueError(
                "No YouTube channels configured! Set YOUTUBE_CHANNELS in your .env file or pass --channel."
            )

        if "pinterest" in self.enabled_sources and not self.pinterest_keywords:
            raise ValueError("No Pinterest keywords configured! Set PINTEREST_KEYWORDS in your configuration.")

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
                    "Tip: Run with --dry-run to test discovery without credentials."
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

    # Source flags
    youtube_enabled = _parse_bool(os.getenv("YOUTUBE_ENABLED", "true"), default=True)
    pinterest_enabled = _parse_bool(os.getenv("PINTEREST_ENABLED", "true"), default=True)
    instagram_enabled = _parse_bool(os.getenv("INSTAGRAM_ENABLED", "true"), default=True)
    raw_sources = os.getenv("ENABLED_SOURCES", "youtube,pinterest,instagram")
    enabled_sources = _parse_sources(raw_sources, youtube_enabled, pinterest_enabled, instagram_enabled)

    # Keywords configuration
    kw_file_path = os.getenv("PINTEREST_KEYWORDS_FILE", "pinterest_keywords.txt")
    kw_path = Path(kw_file_path) if kw_file_path else None
    pinterest_keywords = _parse_keywords(
        os.getenv("PINTEREST_KEYWORDS"),
        keywords_file=kw_path,
        env_file=target_env,
    )

    # Resolution configuration
    raw_min_res = os.getenv("MIN_VIDEO_RESOLUTION")
    if raw_min_res and raw_min_res.strip().isdigit():
        min_video_resolution = int(raw_min_res.strip())
    else:
        dl_q = os.getenv("DOWNLOAD_QUALITY", "1080p").lower()
        if "720" in dl_q:
            min_video_resolution = 720
        elif "480" in dl_q:
            min_video_resolution = 480
        else:
            min_video_resolution = 1080

    max_audio_str = os.getenv("MAX_AUDIO_DURATION_SECONDS")
    max_audio_duration_seconds = int(max_audio_str.strip()) if max_audio_str and max_audio_str.strip().isdigit() else None

    return AppConfig(
        enabled_sources=enabled_sources,
        pinterest_enabled=pinterest_enabled,
        youtube_enabled=youtube_enabled,
        instagram_enabled=instagram_enabled,
        prefer_vertical=_parse_bool(os.getenv("PREFER_VERTICAL", "true"), default=True),
        min_video_duration_seconds=int(os.getenv("MIN_VIDEO_DURATION_SECONDS", "10")),
        max_video_duration_seconds=int(os.getenv("MAX_VIDEO_DURATION_SECONDS", "30")),
        min_video_resolution=min_video_resolution,
        instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN"),
        instagram_account_id=os.getenv("INSTAGRAM_ACCOUNT_ID") or DEFAULT_INSTAGRAM_ACCOUNT_ID,
        instagram_api_base_url=os.getenv("INSTAGRAM_API_BASE_URL", "https://graph.facebook.com/v21.0"),
        instagram_audio_manifest_path=Path(os.getenv("INSTAGRAM_AUDIO_MANIFEST_PATH", "audio_manifest.json")),
        instagram_audio_type=os.getenv("INSTAGRAM_AUDIO_TYPE", "original_sound").strip(),
        min_audio_duration_seconds=int(os.getenv("MIN_AUDIO_DURATION_SECONDS", "5")),
        max_audio_duration_seconds=max_audio_duration_seconds,
        pinterest_keywords=pinterest_keywords,
        pinterest_keywords_file=kw_file_path,
        pinterest_access_token=os.getenv("PINTEREST_ACCESS_TOKEN"),
        pinterest_session_cookie=os.getenv("PINTEREST_SESSION_COOKIE"),
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
        concurrent_fragment_downloads=int(os.getenv("CONCURRENT_FRAGMENT_DOWNLOADS", "8")),
        discovery_max_workers=int(os.getenv("DISCOVERY_MAX_WORKERS", "6")),
        discovery_candidate_pool=int(os.getenv("DISCOVERY_CANDIDATE_POOL", "30")),
        google_service_account_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
        google_service_account_json=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        google_refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        google_token_file=os.getenv("GOOGLE_TOKEN_FILE"),
    )
