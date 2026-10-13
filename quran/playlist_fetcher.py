"""Just-in-time playlist downloader module.
Downloads strictly ONE video at next_index (plus caches rolling buffer of next 2-3 videos)
using yt-dlp per Contract Section 6, Step 2.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yt_dlp

from config import AppConfig, load_config
from logger import get_logger
from quran.state import StateManager

logger = get_logger("quran_playlist")

DEFAULT_QURAN_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLCbY-2p0MeRQ"
FORMAT_SELECTOR = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"


class VideoUnavailableError(Exception):
    """Raised when a video at playlist index is private, deleted, or blocked."""
    pass


class PlaylistFetcher:
    """Manages just-in-time downloading for playlist entries."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        state_mgr: Optional[StateManager] = None,
        download_dir: Optional[Path] = None,
    ) -> None:
        self.config = config or load_config()
        self.state_mgr = state_mgr or StateManager()
        self.download_dir = download_dir or (self.config.temp_dir / "quran_playlist_downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def download_next_video(
        self,
        playlist_url: Optional[str] = None,
        override_video_url: Optional[str] = None,
    ) -> Tuple[Path, Dict[str, Any]]:
        """Download strictly the next video at next_index (or override_video_url).

        Returns:
            Tuple of (downloaded_video_path, video_metadata_dict).
        """
        # If a single video URL is provided (e.g. CLI or dry-run test)
        if override_video_url:
            return self._download_single_video(override_video_url)

        target_playlist = playlist_url or self.state_mgr.state.playlist_url or os.getenv("QURAN_PLAYLIST_URL", DEFAULT_QURAN_PLAYLIST_URL)
        if not self.state_mgr.state.playlist_url:
            self.state_mgr.state.playlist_url = target_playlist
            self.state_mgr.save()

        max_skip_attempts = 15

        for _ in range(max_skip_attempts):
            curr_index = self.state_mgr.state.next_index
            logger.info(
                f"Just-In-Time download: Fetching video at playlist index {curr_index} from {target_playlist}..."
            )

            try:
                downloaded_file, meta = self._download_index(target_playlist, curr_index)
                logger.info(
                    f"Successfully downloaded playlist index {curr_index}: '{meta.get('title')}' -> {downloaded_file.name}"
                )
                # Prefetch rolling buffer of next 2-3 videos metadata in background
                self._update_rolling_buffer(target_playlist, curr_index + 1, curr_index + 3)
                return downloaded_file, meta

            except VideoUnavailableError as e:
                logger.warning(
                    f"Video at playlist index {curr_index} is unavailable ({e}). Skipping index and continuing..."
                )
                self.state_mgr.advance_index()

            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ("private", "deleted", "blocked", "unavailable", "copyright")):
                    logger.warning(
                        f"Video at playlist index {curr_index} is blocked/unavailable. Skipping index: {e}"
                    )
                    self.state_mgr.advance_index()
                else:
                    raise

        raise RuntimeError(f"Exceeded {max_skip_attempts} consecutive unavailable videos in playlist.")

    def _download_index(self, playlist_url: str, index: int) -> Tuple[Path, Dict[str, Any]]:
        """Download single video at 1-based playlist index using yt-dlp."""
        out_template = str(self.download_dir / f"idx_{index}_%(id)s.%(ext)s")

        ydl_opts: Dict[str, Any] = {
            "format": FORMAT_SELECTOR,
            "outtmpl": out_template,
            "playlist_items": str(index),
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(playlist_url, download=True)
            except Exception as e:
                raise VideoUnavailableError(f"Extraction failed at index {index}: {e}")

            if not info:
                raise VideoUnavailableError(f"No info returned for index {index}")

            entries = info.get("entries", [])
            entry = entries[0] if entries else info
            if not entry:
                raise VideoUnavailableError(f"Empty entry at index {index}")

            vid_id = entry.get("id")
            title = entry.get("title", f"Video {vid_id}")
            # Locate downloaded file
            matches = list(self.download_dir.glob(f"idx_{index}_{vid_id}.*"))
            if not matches:
                matches = list(self.download_dir.glob(f"*{vid_id}*"))

            if not matches or not matches[0].exists():
                raise VideoUnavailableError(f"Target download file for index {index} ({vid_id}) not found on disk.")

            target_file = matches[0]
            metadata = {
                "id": vid_id,
                "title": title,
                "playlist_index": index,
                "duration": entry.get("duration"),
                "uploader": entry.get("uploader"),
                "webpage_url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
            }
            return target_file, metadata

    def _download_single_video(self, video_url: str) -> Tuple[Path, Dict[str, Any]]:
        """Download an explicit single video URL."""
        out_template = str(self.download_dir / "single_%(id)s.%(ext)s")
        ydl_opts: Dict[str, Any] = {
            "format": FORMAT_SELECTOR,
            "outtmpl": out_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            vid_id = info.get("id")
            title = info.get("title", f"Video {vid_id}")
            matches = list(self.download_dir.glob(f"*{vid_id}*"))
            if not matches:
                raise RuntimeError(f"Downloaded single video file not found for {vid_id}")
            meta = {
                "id": vid_id,
                "title": title,
                "playlist_index": None,
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "webpage_url": info.get("webpage_url") or video_url,
            }
            return matches[0], meta

    def _update_rolling_buffer(self, playlist_url: str, start_idx: int, end_idx: int) -> None:
        """Fetch metadata for rolling buffer (next 2-3 videos) without downloading media."""
        try:
            ydl_opts = {
                "extract_flat": True,
                "playlist_items": f"{start_idx}:{end_idx}",
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(playlist_url, download=False)
                entries = res.get("entries", [])
                buffer_list = []
                for e in entries:
                    if e:
                        buffer_list.append({
                            "id": e.get("id"),
                            "title": e.get("title"),
                            "url": e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}",
                        })
                self.state_mgr.state.rolling_buffer = buffer_list
                self.state_mgr.save()
        except Exception as e:
            logger.debug(f"Rolling buffer prefetch notice: {e}")
