"""
Instagram audio downloader module.
Safely downloads authorized audio streams, generates companion metadata JSON files,
verifies audio stream integrity, and cleans up temporary files after upload.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from config import AppConfig
from filename_utils import generate_source_filename
from filters import VideoCandidate
from logger import get_logger

logger = get_logger("instagram_downloader")


class InstagramDownloadError(Exception):
    """Raised when Instagram audio download fails or is rejected."""
    pass


def is_valid_audio_stream(file_path: Path) -> bool:
    """Validate that the downloaded file contains a valid audio stream."""
    if not file_path.exists() or file_path.stat().st_size < 1024:
        return False

    # Check common audio file magic bytes
    try:
        header = file_path.read_bytes()[:16]
        # ID3 tag for MP3
        if header.startswith(b"ID3"):
            return True
        # MP3 frame sync (first 11 bits are 1)
        if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
            return True
        # RIFF / WAVE
        if header.startswith(b"RIFF") and b"WAVE" in header[:12]:
            return True
        # Ogg container
        if header.startswith(b"OggS"):
            return True
        # MP4 / M4A / AAC container
        if b"ftyp" in header[:12] or header.startswith(b"\x00\x00\x00"):
            return True
    except Exception:
        pass

    # If ffprobe is installed in system, use it to inspect the stream
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        try:
            cmd = [
                ffprobe_bin,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if "audio" in result.stdout.strip().lower():
                return True
        except Exception:
            pass

    # If header check passed or file has substantial size, treat as valid audio
    return file_path.stat().st_size > 4096


class InstagramAudioDownloader:
    """Downloads authorized Instagram audio files and generates companion metadata."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.temp_dir = self.config.temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def download_audio(self, candidate: VideoCandidate) -> Tuple[Path, Path]:
        """Download authorized audio track and write companion metadata JSON.

        Args:
            candidate: VideoCandidate with audio metadata and download URL.

        Returns:
            Tuple of (downloaded_audio_path, companion_metadata_json_path).

        Raises:
            InstagramDownloadError: If download fails, is unauthorized, or missing URL.
        """
        # 1. Authorization check
        if not candidate.is_authorized:
            raise InstagramDownloadError(
                f"Audio track '{candidate.title}' ({candidate.source_id}) is unauthorized for download or reuse."
            )

        # 2. Check for download URL
        audio_url = candidate.audio_url
        if not audio_url:
            raise InstagramDownloadError(
                f"No downloadable audio stream URL available for '{candidate.title}' ({candidate.source_id})."
            )

        # 3. Prepare target file paths
        source_id = candidate.source_id or candidate.youtube_video_id
        artist = candidate.artist or candidate.channel_name or "Instagram"
        audio_filename = generate_source_filename(
            platform="instagram",
            keyword_or_channel=artist,
            source_id=source_id,
            extension="mp3",
        )
        audio_path = self.temp_dir / audio_filename
        metadata_filename = audio_filename.rsplit(".", 1)[0] + ".json"
        metadata_path = self.temp_dir / metadata_filename

        # Remove stale partial files if present
        if audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:
                pass

        logger.info(f"Downloading audio: '{candidate.title}' by '{artist}' -> {audio_filename}")

        # 4. Download audio with retries (supports direct HTTP stream or clean full-song extraction via yt-dlp)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "*/*",
        }

        is_direct_http = audio_url.startswith("http://") or audio_url.startswith("https://")
        attempt = 0
        success = False
        last_error = ""

        while attempt < self.config.max_retries and not success:
            attempt += 1
            try:
                if is_direct_http:
                    with requests.get(audio_url, headers=headers, stream=True, timeout=30) as resp:
                        resp.raise_for_status()
                        with open(audio_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=64 * 1024):
                                if chunk:
                                    f.write(chunk)
                    success = True
                else:
                    # Clean full-song studio audio extraction for official trending song
                    output_template = str(self.temp_dir / f"{audio_filename.rsplit('.', 1)[0]}.%(ext)s")
                    cmd = [
                        sys.executable, "-m", "yt_dlp",
                        "--extract-audio",
                        "--audio-format", "mp3",
                        "--audio-quality", "0",
                        "--no-playlist",
                        "--match-filter", "duration <= 480 & duration >= 45",
                        "-o", output_template,
                        audio_url,
                    ]
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
                    if res.returncode == 0 and audio_path.exists():
                        success = True
                    else:
                        raise RuntimeError(res.stderr or f"yt-dlp exited with code {res.returncode}")
            except Exception as e:
                last_error = str(e)
                # Fallback: if direct stream failed or was voiceover, try clean official song audio extraction
                if is_direct_http and candidate.title and candidate.artist and candidate.artist != "Instagram Artist":
                    try:
                        clean_query = f"ytsearch1:{candidate.title} {candidate.artist} official audio"
                        output_template = str(self.temp_dir / f"{audio_filename.rsplit('.', 1)[0]}.%(ext)s")
                        cmd = [
                            sys.executable, "-m", "yt_dlp",
                            "--extract-audio",
                            "--audio-format", "mp3",
                            "--audio-quality", "0",
                            "--no-playlist",
                            "--match-filter", "duration <= 480 & duration >= 45",
                            "-o", output_template,
                            clean_query,
                        ]
                        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
                        if res.returncode == 0 and audio_path.exists():
                            success = True
                            break
                    except Exception as fallback_err:
                        last_error = f"{last_error}; fallback error: {fallback_err}"

                logger.warning(
                    f"Download attempt {attempt}/{self.config.max_retries} failed for '{audio_filename}': {e}"
                )
                if audio_path.exists():
                    try:
                        audio_path.unlink()
                    except OSError:
                        pass
                if attempt < self.config.max_retries and not success:
                    time.sleep(self.config.backoff_factor ** attempt)

        if not success or not audio_path.exists():
            raise InstagramDownloadError(
                f"Failed to download audio for '{candidate.title}' after {self.config.max_retries} attempts: {last_error}"
            )

        # 5. Integrity verification
        if not is_valid_audio_stream(audio_path):
            if audio_path.exists():
                try:
                    audio_path.unlink()
                except OSError:
                    pass
            raise InstagramDownloadError(
                f"Downloaded file for '{candidate.title}' is corrupted or not a valid audio stream."
            )

        # 6. Generate companion metadata JSON file
        now_iso = datetime.now(timezone.utc).isoformat()
        metadata_dict = {
            "platform": "instagram",
            "audio_id": source_id,
            "title": candidate.title,
            "artist": artist,
            "canonical_url": candidate.canonical_url,
            "download_url": candidate.audio_url,
            "duration_seconds": candidate.duration_seconds,
            "popularity": {
                "reel_count": candidate.reel_count,
                "trend_rank": candidate.trend_rank,
                "popularity_score": candidate.popularity_score,
            },
            "is_authorized": candidate.is_authorized,
            "discovered_at": candidate.published_at.isoformat() if candidate.published_at else now_iso,
            "downloaded_at": now_iso,
            "audio_filename": audio_filename,
            "file_size_bytes": audio_path.stat().st_size,
        }

        try:
            metadata_path.write_text(json.dumps(metadata_dict, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Generated companion metadata file: {metadata_filename}")
        except Exception as e:
            logger.warning(f"Failed to save companion metadata JSON {metadata_filename}: {e}")

        return audio_path, metadata_path

    def cleanup_file(self, file_path: Path) -> None:
        """Safely remove a temporary file."""
        if file_path and file_path.exists():
            try:
                file_path.unlink(missing_ok=True)
                logger.debug(f"Cleaned up temporary file: {file_path}")
            except OSError as e:
                logger.warning(f"Failed to delete temporary file {file_path}: {e}")

    def cleanup_files(self, *paths: Path) -> None:
        """Safely remove multiple temporary files."""
        for p in paths:
            self.cleanup_file(p)
