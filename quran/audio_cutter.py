"""Audio cutting module for Quran recitation reels.
Executes precision audio trimming (start-0.3s to end+0.3s) with audio crossfades
and 8-40s sanity gating per Contract Section 6, Step 6.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from logger import get_logger

logger = get_logger("quran_audio_cutter")

MIN_AUDIO_DURATION = 8.0
MAX_AUDIO_DURATION = 40.0
FADE_DURATION = 0.3


def cut_recitation_audio(
    source_media_path: Path,
    start_time: float,
    end_time: float,
    output_audio_path: Optional[Path] = None,
) -> Tuple[Path, float]:
    """Trim audio with 0.3s lead/tail padding, short fade-in/out, and duration sanity checks.

    Args:
        source_media_path: Source video or audio file.
        start_time: Recitation start timestamp (seconds).
        end_time: Translation end timestamp (seconds).
        output_audio_path: Destination path for trimmed audio.

    Returns:
        Tuple of (output_audio_path, duration_seconds).

    Raises:
        ValueError: If duration does not pass the 8-40s sanity gate.
        RuntimeError: If FFmpeg trimming fails.
    """
    padded_start = max(0.0, start_time - FADE_DURATION)
    padded_end = end_time + FADE_DURATION
    duration = padded_end - padded_start

    # Contract Sanity Gate: 8-40s
    if duration < MIN_AUDIO_DURATION:
        raise ValueError(
            f"Audio duration ({duration:.2f}s) is below minimum sanity threshold of {MIN_AUDIO_DURATION}s."
        )
    if duration > MAX_AUDIO_DURATION:
        raise ValueError(
            f"Audio duration ({duration:.2f}s) exceeds maximum sanity threshold of {MAX_AUDIO_DURATION}s."
        )

    if not output_audio_path:
        output_audio_path = source_media_path.with_name(
            f"ayah_cut_{int(start_time)}_{int(end_time)}.mp3"
        )

    fade_out_start = max(0.0, duration - FADE_DURATION)
    audio_filter = f"afade=t=in:st=0:d={FADE_DURATION},afade=t=out:st={fade_out_start:.2f}:d={FADE_DURATION}"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{padded_start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source_media_path),
        "-vn",
        "-af",
        audio_filter,
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(output_audio_path),
    ]

    logger.info(
        f"Trimming audio from {padded_start:.2f}s to {padded_end:.2f}s (duration: {duration:.2f}s) with fades..."
    )
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio cut failed: {proc.stderr.strip()[-200:]}")

    if not output_audio_path.exists() or output_audio_path.stat().st_size == 0:
        raise RuntimeError(f"Trimmed audio file missing or empty: {output_audio_path}")

    return output_audio_path, duration
