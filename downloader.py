"""
Video downloader module using yt-dlp with exponential backoff retry,
stream merging, temporary file safety, and format verification.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp

from config import AppConfig
from filename_utils import generate_video_filename, sanitize_filename
from filters import VideoCandidate
from logger import get_logger

logger = get_logger("downloader")


class DownloadError(Exception):
    """Custom exception raised when video download fails permanently."""
    pass


class VideoDownloader:
    """Manages secure, verified video downloads into temporary workspace."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.temp_dir = Path(config.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _build_format_selector(self) -> str:
        """Construct format selector prioritizing MP4 H.264/AAC for maximum Drive compatibility."""
        quality = self.config.download_quality.lower()
        if "720" in quality:
            max_height = 720
        elif "480" in quality:
            max_height = 480
        elif "best" in quality or "max" in quality:
            max_height = 2160
        else:
            max_height = 1080

        # Preference: MP4 AVC1 video + M4A audio -> Any MP4 video + best audio -> Best MP4
        return (
            f"bestvideo[ext=mp4][vcodec^=avc1][height<={max_height}]+bestaudio[ext=m4a]/"
            f"bestvideo[ext=mp4][height<={max_height}]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={max_height}]+bestaudio/"
            f"best[ext=mp4][height<={max_height}]/"
            f"best[height<={max_height}]/best"
        )

    def download_video(
        self,
        candidate: VideoCandidate,
    ) -> Path:
        """Download video with retries, exponential backoff, and atomic verification.

        Args:
            candidate: VideoCandidate to download.

        Returns:
            Path to the downloaded, verified MP4 file in the temporary directory.

        Raises:
            DownloadError: If download fails after all retry attempts.
        """
        video_id = candidate.youtube_video_id
        target_filename = generate_video_filename(
            channel_name=candidate.channel_name,
            title=candidate.title,
            youtube_video_id=video_id,
            extension="mp4",
        )
        final_file_path = self.temp_dir / target_filename
        part_template = self.temp_dir / f"{video_id}.download.%(ext)s"

        # If file already exists and is non-empty, reuse it
        if final_file_path.exists() and final_file_path.stat().st_size > 1024 * 1024:
            logger.info(f"Existing verified download found at {final_file_path}")
            return final_file_path

        format_str = self._build_format_selector()
        ydl_opts: Dict[str, Any] = {
            "format": format_str,
            "outtmpl": str(part_template),
            "merge_output_format": "mp4",
            "quiet": False,
            "no_warnings": False,
            "retries": 5,
            "fragment_retries": 5,
            "socket_timeout": 30,
            # Prevent lingering partial downloads on uncaught aborts
            "nopart": False,
            "concurrent_fragment_downloads": getattr(self.config, "concurrent_fragment_downloads", 8),
            "buffersize": 1024 * 64,
        }

        last_error: Optional[Exception] = None
        attempt = 0

        while attempt < self.config.max_retries:
            attempt += 1
            logger.info(
                f"Download attempt {attempt}/{self.config.max_retries} for "
                f"'{candidate.title}' ({video_id})"
            )

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    exit_code = ydl.download([candidate.youtube_url])
                    if exit_code != 0:
                        raise DownloadError(f"yt-dlp exited with status code {exit_code}")

                # Locate downloaded file (could have ended up as mp4 or mkv before merge)
                possible_files = list(self.temp_dir.glob(f"{video_id}.download.*"))
                completed_files = [
                    f for f in possible_files
                    if not f.name.endswith(".part") and not f.name.endswith(".ytdl")
                ]

                if not completed_files:
                    raise DownloadError("Download finished but no output file found")

                source_file = completed_files[0]

                # Verify file size is valid (> 100 KB)
                file_size = source_file.stat().st_size
                if file_size < 100 * 1024:
                    raise DownloadError(f"Downloaded file is suspiciously small ({file_size} bytes)")

                # Move/rename atomically to clean final filename
                if source_file != final_file_path:
                    if final_file_path.exists():
                        final_file_path.unlink()
                    shutil.move(str(source_file), str(final_file_path))

                logger.info(
                    f"Successfully downloaded '{final_file_path.name}' "
                    f"({file_size / (1024 * 1024):.2f} MB)"
                )
                return final_file_path

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Download attempt {attempt} failed for {video_id}: {e}"
                )

                # Clean up any partial files for this video
                for part_file in self.temp_dir.glob(f"{video_id}.download.*"):
                    try:
                        part_file.unlink(missing_ok=True)
                    except OSError:
                        pass

                if attempt < self.config.max_retries:
                    sleep_time = self.config.backoff_factor ** attempt
                    logger.info(f"Retrying download in {sleep_time:.1f} seconds...")
                    time.sleep(sleep_time)

        raise DownloadError(
            f"Failed to download video {video_id} after {self.config.max_retries} attempts: {last_error}"
        )

    def cleanup_file(self, file_path: Path) -> None:
        """Safely remove a temporary file after successful upload."""
        try:
            if file_path.exists():
                file_path.unlink(missing_ok=True)
                logger.debug(f"Removed temporary file {file_path}")
        except Exception as e:
            logger.warning(f"Could not remove temporary file {file_path}: {e}")
