"""Groq Whisper transcription module.
Extracts audio and calls Groq Whisper (whisper-large-v3-turbo) with verbose timestamps
per Contract Section 6, Step 3.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from logger import get_logger
from quran.key_rotator import get_key_rotator

logger = get_logger("quran_transcribe")

GROQ_TRANSCRIPTIONS_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-large-v3-turbo"


@dataclass
class TranscriptSegment:
    """A timestamped segment from Whisper."""

    id: int
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    """Full transcription output."""

    text: str
    segments: List[TranscriptSegment]
    duration_seconds: float


def extract_audio_for_whisper(video_path: Path, output_audio_path: Optional[Path] = None) -> Path:
    """Extract compressed 16kHz mono audio from video file using ffmpeg for optimal Whisper speed."""
    if not output_audio_path:
        output_audio_path = video_path.with_suffix(".whisper.mp3")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-b:a",
        "64k",
        str(output_audio_path),
    ]

    logger.info(f"Extracting audio from {video_path.name} to {output_audio_path.name}...")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {proc.stderr.strip()[-200:]}")

    if not output_audio_path.exists() or output_audio_path.stat().st_size == 0:
        raise RuntimeError(f"Extracted audio file is missing or empty: {output_audio_path}")

    return output_audio_path


def transcribe_audio(
    audio_path: Path,
    language_hint: Optional[str] = None,
    max_retries: int = 3,
) -> TranscriptionResult:
    """Transcribe audio file using Groq Whisper with verbose segment timestamps."""
    rotator = get_key_rotator()
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        api_key = rotator.get_current_key()
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            with open(audio_path, "rb") as f:
                files = {
                    "file": (audio_path.name, f, "audio/mpeg"),
                }
                data = {
                    "model": WHISPER_MODEL,
                    "response_format": "verbose_json",
                    "temperature": "0.0",
                }
                if language_hint:
                    data["language"] = language_hint

                logger.info(
                    f"Sending audio ({audio_path.stat().st_size / 1024:.1f} KB) to Groq Whisper ({WHISPER_MODEL})..."
                )
                resp = requests.post(
                    GROQ_TRANSCRIPTIONS_ENDPOINT,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=180,
                )

            if resp.status_code == 200:
                result_json = resp.json()
                raw_segments = result_json.get("segments", [])
                segments: List[TranscriptSegment] = []
                for s in raw_segments:
                    segments.append(
                        TranscriptSegment(
                            id=int(s.get("id", len(segments))),
                            start=float(s.get("start", 0.0)),
                            end=float(s.get("end", 0.0)),
                            text=str(s.get("text", "")).strip(),
                        )
                    )

                full_text = result_json.get("text", "")
                duration = float(result_json.get("duration", 0.0))
                logger.info(
                    f"Whisper transcription complete: {len(segments)} segments, duration: {duration:.1f}s."
                )
                return TranscriptionResult(
                    text=full_text,
                    segments=segments,
                    duration_seconds=duration,
                )

            if resp.status_code in (429, 401):
                err_msg = f"HTTP {resp.status_code}: {resp.text}"
                rotator.rotate_key(reason=f"Whisper API error: {err_msg}")
                time.sleep(1.0)
                continue

            resp.raise_for_status()

        except Exception as e:
            last_error = e
            logger.warning(f"Whisper attempt {attempt + 1} failed: {e}")
            rotator.rotate_key(reason=str(e))
            time.sleep(1.5)

    raise RuntimeError(f"All Groq Whisper transcription attempts failed: {last_error}")
