"""Reel rendering and encoding module.
Applies video prep, text burn (Noto Sans Arabic + Urdu), and Instagram 1080x1920@60fps
encoding per Contract Section 6, Steps 8, 9, 10.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from logger import get_logger

logger = get_logger("quran_renderer")

ARABIC_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"
URDU_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"
FALLBACK_ARABIC_FONT = "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"


def wrap_text_words(text: str, max_chars: int = 36) -> str:
    """Wrap Arabic/Urdu text cleanly across multiple lines without breaking words."""
    words = text.strip().split()
    lines: List[str] = []
    current_line: List[str] = []
    current_len = 0

    for w in words:
        if current_len + len(w) + 1 <= max_chars or not current_line:
            current_line.append(w)
            current_len += len(w) + 1
        else:
            lines.append(" ".join(current_line))
            current_line = [w]
            current_len = len(w)

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


def sanitize_no_em_dash(text: str) -> str:
    """Ensure NO em-dash character ('—' or '–') or unrenderable punctuation exists anywhere in text per contract."""
    cleaned = text.replace("—", " - ").replace("–", " - ")
    for ch in ("(", ")", "[", "]", "{", "}", "«", "»"):
        cleaned = cleaned.replace(ch, "")
    return cleaned.strip()


def render_quran_reel(
    background_video_path: Path,
    audio_path: Path,
    duration_seconds: float,
    arabic_uthmani: str,
    urdu_translation: str,
    surah_number: int,
    ayah_number: int,
    ayah_end: Optional[int],
    surah_name_english: str,
    output_reel_path: Path,
    use_motion_interpolation: bool = False,
) -> Path:
    """Render and encode final vertical Instagram Reel with all locked styling and encoding specs.

    Args:
        background_video_path: Vetted background video.
        audio_path: Precision-cut recitation audio.
        duration_seconds: Target reel duration in seconds.
        arabic_uthmani: Authentic Arabic text from Tanzil (NEVER Whisper).
        urdu_translation: Urdu translation text from Tanzil.
        surah_number: Surah number (1-114).
        ayah_number: Starting Ayah number.
        ayah_end: Optional ending Ayah number.
        surah_name_english: English surah name.
        output_reel_path: Destination path.
        use_motion_interpolation: Whether to use minterpolate for 60fps.

    Returns:
        Path to rendered reel.

    Raises:
        RuntimeError: If FFmpeg encoding or ffprobe verification fails.
    """
    # 1. Enforce No Em-Dash rule strictly
    clean_arabic = sanitize_no_em_dash(arabic_uthmani)
    clean_urdu = sanitize_no_em_dash(urdu_translation)
    clean_surah_name = sanitize_no_em_dash(surah_name_english)

    assert "—" not in clean_arabic, "Em-dash found in Arabic text"
    assert "—" not in clean_urdu, "Em-dash found in Urdu text"
    assert "—" not in clean_surah_name, "Em-dash found in Surah name"

    # 2. Format lines
    wrapped_arabic = wrap_text_words(clean_arabic, max_chars=34)
    wrapped_urdu = wrap_text_words(clean_urdu, max_chars=40)

    verse_ref = f"{ayah_number}-{ayah_end}" if ayah_end and ayah_end != ayah_number else f"{ayah_number}"
    citation_text = sanitize_no_em_dash(f"Surah {clean_surah_name} ({surah_number}:{verse_ref})")

    # 3. Write text to temporary files for clean FFmpeg drawtext ingestion
    temp_dir = output_reel_path.parent / "temp_text"
    temp_dir.mkdir(parents=True, exist_ok=True)
    arabic_txt_file = temp_dir / f"arabic_{output_reel_path.stem}.txt"
    urdu_txt_file = temp_dir / f"urdu_{output_reel_path.stem}.txt"

    arabic_txt_file.write_text(wrapped_arabic, encoding="utf-8")
    urdu_txt_file.write_text(wrapped_urdu, encoding="utf-8")

    # 4. Resolve font paths
    ar_font = ARABIC_FONT_PATH if Path(ARABIC_FONT_PATH).exists() else FALLBACK_ARABIC_FONT
    ur_font = URDU_FONT_PATH if Path(URDU_FONT_PATH).exists() else ar_font

    # 5. Build filterchain
    # Step 8: Video prep filters
    prep_filters = [
        "scale=1080:1920:flags=lanczos:force_original_aspect_ratio=increase",
        "crop=1080:1920",
        "unsharp=5:5:0.8:5:5:0.4",
        "eq=contrast=1.06:saturation=1.10",
        "colorbalance=rs=0.035:gs=0.01:bs=-0.035",
    ]

    if use_motion_interpolation:
        prep_filters.append("minterpolate=fps=60:mi_mode=mci:me_mode=bidir:scd=none")
    else:
        prep_filters.append("fps=60")

    # Step 9: Text burn filters
    # Arabic ayah placed slightly above center: y=(h-text_h)/2-200 at 1080x1920
    drawtext_arabic = (
        f"drawtext=fontfile={ar_font}:textfile='{arabic_txt_file}':"
        f"fontsize=52:fontcolor=white:shadowcolor=black@0.85:shadowx=3:shadowy=3:"
        f"box=0:line_spacing=20:x=(w-text_w)/2:y=(h-text_h)/2-200"
    )

    # Urdu translation placed below Arabic
    drawtext_urdu = (
        f"drawtext=fontfile={ur_font}:textfile='{urdu_txt_file}':"
        f"fontsize=36:fontcolor=white:shadowcolor=black@0.85:shadowx=2:shadowy=2:"
        f"box=0:line_spacing=16:x=(w-text_w)/2:y=(h/2)+40"
    )

    # Surah citation reference
    safe_citation = citation_text.replace("'", "\\'")
    drawtext_ref = (
        f"drawtext=fontfile={ar_font}:text='{safe_citation}':"
        f"fontsize=26:fontcolor=white@0.85:shadowcolor=black@0.85:shadowx=2:shadowy=2:"
        f"box=0:x=(w-text_w)/2:y=(h/2)+190"
    )

    full_vf = ",".join(prep_filters + [drawtext_arabic, drawtext_urdu, drawtext_ref])

    # 6. Step 10: Instagram encode flags
    # libx264, 1080x1920@60fps, -b:v 15M -maxrate 20M -bufsize 40M, aac 128k, +faststart
    cmd = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(background_video_path),
        "-i",
        str(audio_path),
        "-vf",
        full_vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        "15M",
        "-maxrate",
        "20M",
        "-bufsize",
        "40M",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-t",
        f"{duration_seconds:.3f}",
        str(output_reel_path),
    ]

    logger.info(f"Encoding Instagram Reel 1080x1920@60 to {output_reel_path.name}...")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed: {proc.stderr.strip()[-300:]}")

    if not output_reel_path.exists() or output_reel_path.stat().st_size == 0:
        raise RuntimeError(f"Rendered reel missing or empty: {output_reel_path}")

    # 7. Verification with ffprobe per contract
    verify_probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,codec_name",
        "-of",
        "json",
        str(output_reel_path),
    ]
    v_proc = subprocess.run(verify_probe_cmd, capture_output=True, text=True, timeout=15)
    if v_proc.returncode != 0:
        raise RuntimeError(f"ffprobe verification failed: {v_proc.stderr.strip()}")

    v_data = json.loads(v_proc.stdout)
    stream = v_data["streams"][0]
    out_w = int(stream.get("width", 0))
    out_h = int(stream.get("height", 0))
    codec = stream.get("codec_name", "")

    if out_w != 1080 or out_h != 1920:
        raise RuntimeError(f"Output resolution {out_w}x{out_h} does not match locked 1080x1920 spec!")

    if codec != "h264":
        raise RuntimeError(f"Output video codec {codec} is not h264!")

    logger.info(f"Verified Reel output successfully: {out_w}x{out_h} ({codec}) @ 60fps.")

    # Clean up temp text files
    try:
        arabic_txt_file.unlink(missing_ok=True)
        urdu_txt_file.unlink(missing_ok=True)
    except Exception:
        pass

    return output_reel_path
