"""
Pinterest video downloader module.
Handles downloading genuine video media using yt-dlp, format selection,
FFprobe-based media verification, temporary file safety, and exponential backoff retry.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yt_dlp

from config import AppConfig
from filename_utils import generate_source_filename, sanitize_filename
from filters import VideoCandidate
from logger import get_logger

logger = get_logger("pinterest_downloader")


class PinterestDownloadError(Exception):
    """Raised when a Pinterest video download fails or fails validation."""
    pass


def validate_media_with_ffprobe(file_path: Path) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Validate that the downloaded file is a genuine, uncorrupted video using FFprobe.

    Args:
        file_path: Path to the media file to inspect.

    Returns:
        Tuple of:
        - Boolean indicating whether file is a valid video
        - Error message if invalid, or None if valid
        - Dictionary of extracted video metadata (width, height, duration, codec)
    """
    if not file_path.exists():
        return False, f"File does not exist: {file_path}", {}

    file_size = file_path.stat().st_size
    # Video files should not be tiny preview stubs or thumbnails
    if file_size < 50 * 1024:
        return False, f"File is suspiciously small for a video ({file_size} bytes)", {}

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,duration",
        "-show_entries",
        "format=format_name,duration,size",
        "-of",
        "json",
        str(file_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return False, f"FFprobe returned error code {proc.returncode}: {proc.stderr.strip()}", {}

        data = json.loads(proc.stdout)
        streams = data.get("streams", [])
        if not streams:
            return False, "FFprobe detected no video streams in downloaded file (possible image or audio-only)", {}

        video_stream = streams[0]
        codec = video_stream.get("codec_name")
        width = video_stream.get("width")
        height = video_stream.get("height")

        if not codec:
            return False, "FFprobe could not identify a valid video codec", {}

        if not width or not height or width <= 0 or height <= 0:
            return False, f"Invalid video dimensions: {width}x{height}", {}

        fmt = data.get("format", {})
        duration = None
        if video_stream.get("duration"):
            try:
                duration = float(video_stream["duration"])
            except (ValueError, TypeError):
                pass
        elif fmt.get("duration"):
            try:
                duration = float(fmt["duration"])
            except (ValueError, TypeError):
                pass

        meta = {
            "codec": codec,
            "width": width,
            "height": height,
            "duration": duration,
            "size": file_size,
            "format": fmt.get("format_name"),
        }
        return True, None, meta

    except FileNotFoundError:
        # If FFprobe binary is missing from PATH, fallback to basic file verification
        logger.warning("FFprobe binary not found on system; falling back to basic header verification.")
        try:
            with open(file_path, "rb") as f:
                header = f.read(32)
                # MP4 / ftyp box check
                if b"ftyp" in header or b"moov" in header:
                    return True, None, {"size": file_size, "fallback_check": True}
        except Exception as e:
            return False, f"Header inspection error: {e}", {}
        return False, "File does not contain valid MP4 signatures", {}

    except subprocess.TimeoutExpired:
        return False, "FFprobe validation timed out", {}
    except Exception as e:
        return False, f"Unexpected error during media validation: {e}", {}


class PinterestDownloader:
    """Manages verified downloads of Pinterest video Pins into a temporary workspace."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.temp_dir = Path(config.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _build_format_selector(self) -> str:
        """Construct yt-dlp format selector prioritizing 1080p and highest resolution."""
        quality = self.config.download_quality.lower()
        if "720" in quality:
            return (
                "bestvideo[ext=mp4][height<=1280]+bestaudio[ext=m4a]/"
                "bestvideo[height<=1280]+bestaudio/"
                "best[ext=mp4][height<=1280]/"
                "best[height<=1280]/best"
            )
        elif "480" in quality:
            return (
                "bestvideo[ext=mp4][height<=854]+bestaudio[ext=m4a]/"
                "bestvideo[height<=854]+bestaudio/"
                "best[ext=mp4][height<=854]/"
                "best[height<=854]/best"
            )
        else:
            # 1080p Full HD: Require streams meeting 1080p, prioritizing fast direct HTTP/HTTPS
            return (
                "bestvideo[protocol^=http][width>=1080][height>=1080]+bestaudio[ext=m4a]/"
                "best[protocol^=http][width>=1080][height>=1080]/"
                "bestvideo[width>=1080][height>=1080]+bestaudio[ext=m4a]/"
                "best[width>=1080][height>=1080]/"
                "bestvideo[protocol^=http][width>=1080]+bestaudio[ext=m4a]/"
                "best[protocol^=http][width>=1080]/"
                "bestvideo[width>=1080]+bestaudio[ext=m4a]/"
                "best[width>=1080]"
            )

    def download_video(self, candidate: VideoCandidate) -> Path:
        """Download video Pin with retries, exponential backoff, and FFprobe verification.

        Args:
            candidate: VideoCandidate to download.

        Returns:
            Path to the downloaded, verified MP4 file in the temporary directory.

        Raises:
            PinterestDownloadError: If download fails or fails media verification.
        """
        pin_id = candidate.source_id or candidate.youtube_video_id
        kw = candidate.search_keyword or "nature-aesthetic"

        target_filename = generate_source_filename(
            platform="Pinterest",
            keyword_or_channel=kw,
            source_id=pin_id,
            extension="mp4",
        )
        final_file_path = self.temp_dir / target_filename
        part_template = self.temp_dir / f"pin_{pin_id}.download.%(ext)s"

        # If file already exists and passes validation, reuse it
        if final_file_path.exists() and final_file_path.stat().st_size > 50 * 1024:
            is_valid, _, _ = validate_media_with_ffprobe(final_file_path)
            if is_valid:
                logger.info(f"Existing verified Pinterest download found at {final_file_path}")
                return final_file_path

        format_str = self._build_format_selector()
        ydl_opts: Dict[str, Any] = {
            "format": format_str,
            "format_sort": ["res:1080", "width:1080", "height:1920", "+size", "proto:https"],
            "outtmpl": str(part_template),
            "merge_output_format": "mp4",
            "quiet": False,
            "no_warnings": False,
            "retries": 5,
            "fragment_retries": 5,
            "socket_timeout": 30,
            "nopart": False,
            "concurrent_fragment_downloads": getattr(self.config, "concurrent_fragment_downloads", 8),
            "buffersize": 1024 * 64,
        }

        # Apply cookies only if explicitly configured
        if self.config.pinterest_session_cookie:
            # Pass custom cookie string via http_headers
            ydl_opts["http_headers"] = {"Cookie": self.config.pinterest_session_cookie}

        last_error: Optional[Exception] = None
        attempt = 0

        while attempt < self.config.max_retries:
            attempt += 1
            logger.info(
                f"Pinterest download attempt {attempt}/{self.config.max_retries} for "
                f"'{candidate.title}' (Pin ID: {pin_id})"
            )

            try:
                target_url = candidate.canonical_url or f"https://www.pinterest.com/pin/{pin_id}/"
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    exit_code = ydl.download([target_url])
                    if exit_code != 0:
                        raise PinterestDownloadError(f"yt-dlp exited with code {exit_code}")

                # Locate downloaded output file
                possible_files = list(self.temp_dir.glob(f"pin_{pin_id}.download.*"))
                completed_files = [
                    f for f in possible_files
                    if not f.name.endswith(".part") and not f.name.endswith(".ytdl")
                ]

                if not completed_files:
                    raise PinterestDownloadError("Download finished but no output media file was found")

                source_file = completed_files[0]

                # Atomic move to standardized filename
                if source_file != final_file_path:
                    if final_file_path.exists():
                        final_file_path.unlink()
                    shutil.move(str(source_file), str(final_file_path))

                # Rigorous validation using FFprobe
                is_valid, reason, meta = validate_media_with_ffprobe(final_file_path)
                if not is_valid:
                    # Never mark an invalid media file as successful
                    self.cleanup_file(final_file_path)
                    raise PinterestDownloadError(f"Downloaded file failed validation: {reason}")

                # Enforce 1080p resolution verification via FFprobe
                if self.config.min_video_resolution >= 1080 and meta.get("width") and meta.get("height"):
                    w = meta["width"]
                    h = meta["height"]
                    is_vert = h >= w
                    if is_vert and (w < 1080 and h < 1920):
                        self.cleanup_file(final_file_path)
                        raise PinterestDownloadError(
                            f"Downloaded video resolution {w}x{h} does not meet required 1080p Full HD "
                            f"(expected minimum 1080x1920 vertical, got {w}x{h})"
                        )
                    elif not is_vert and (h < 1080 and w < 1920):
                        self.cleanup_file(final_file_path)
                        raise PinterestDownloadError(
                            f"Downloaded video resolution {w}x{h} does not meet required 1080p Full HD "
                            f"(expected minimum 1920x1080 horizontal, got {w}x{h})"
                        )

                file_size = final_file_path.stat().st_size
                logger.info(
                    f"Successfully downloaded and validated Pinterest video '{final_file_path.name}' "
                    f"({file_size / (1024 * 1024):.2f} MB, codec: {meta.get('codec')}, "
                    f"res: {meta.get('width')}x{meta.get('height')})"
                )
                return final_file_path

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Pinterest download attempt {attempt} failed for {pin_id}: {e}"
                )

                # Clean up partial files
                for part_file in self.temp_dir.glob(f"pin_{pin_id}.download.*"):
                    try:
                        part_file.unlink(missing_ok=True)
                    except OSError:
                        pass

                err_str = str(e).lower()
                is_non_retriable = (
                    "does not meet required" in err_str
                    or "requested format is not available" in err_str
                )
                if is_non_retriable:
                    logger.info(
                        f"Pin {pin_id} does not satisfy required resolution or format; "
                        "skipping retries and proceeding immediately to fallback."
                    )
                    break

                if attempt < self.config.max_retries:
                    sleep_time = self.config.backoff_factor ** attempt
                    logger.info(f"Retrying Pinterest download in {sleep_time:.1f} seconds...")
                    time.sleep(sleep_time)

        raise PinterestDownloadError(
            f"Failed to download Pinterest video {pin_id} after {attempt} attempt(s): {last_error}"
        )

    def cleanup_file(self, file_path: Path) -> None:
        """Safely remove a temporary file after processing."""
        try:
            if file_path.exists():
                file_path.unlink(missing_ok=True)
                logger.debug(f"Removed temporary file {file_path}")
        except Exception as e:
            logger.warning(f"Could not remove temporary file {file_path}: {e}")
