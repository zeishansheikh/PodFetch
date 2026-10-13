"""Manifest management and Google Drive sync module.
Generates ready/manifest.json and validates output files per Contract Section 4.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import AppConfig, load_config
from drive_uploader import GoogleDriveUploader
from logger import get_logger
from quran.renderer import sanitize_no_em_dash

logger = get_logger("quran_manifest")

READY_DIR = Path("ready")


@dataclass
class ReelManifest:
    """Locked manifest schema for Contract Section 4."""

    reel_file: str
    date: str
    surah_number: int
    ayah_number: int
    ayah_end: Optional[int]
    surah_name_english: str
    surah_name_arabic: str
    arabic_text: str
    urdu_translation: str
    caption: str
    hashtags: List[str]
    duration_seconds: float
    drive_file_id: Optional[str] = None
    drive_link: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def validate(self) -> None:
        """Validate all contract constraints."""
        # 1. Exactly 3 hashtags
        if len(self.hashtags) != 3:
            raise ValueError(f"Manifest must contain exactly 3 hashtags, found {len(self.hashtags)}: {self.hashtags}")

        # 2. No em-dash anywhere
        manifest_str = json.dumps(asdict(self), ensure_ascii=False)
        if "—" in manifest_str or "–" in manifest_str:
            raise ValueError("Forbidden em-dash ('—' or '–') found in manifest data!")

        # 3. English caption present
        if not self.caption or not self.caption.strip():
            raise ValueError("Manifest caption cannot be empty!")

        # 4. Authentic Arabic text present
        if not self.arabic_text or not self.arabic_text.strip():
            raise ValueError("Manifest arabic_text cannot be empty!")


class ManifestManager:
    """Validates, writes, and uploads manifest and reel."""

    def __init__(self, config: Optional[AppConfig] = None) -> None:
        self.config = config or load_config()
        self.ready_dir = READY_DIR
        self.uploader = GoogleDriveUploader(self.config)

    def write_and_upload(
        self,
        date_str: str,
        reel_file_path: Path,
        surah_number: int,
        ayah_number: int,
        ayah_end: Optional[int],
        surah_name_english: str,
        surah_name_arabic: str,
        arabic_text: str,
        urdu_translation: str,
        english_caption: str,
        duration_seconds: float,
        hashtags: Optional[List[str]] = None,
    ) -> Tuple[Path, Path, Optional[str], Optional[str]]:
        """Publish final reel and manifest into ready/ directory and upload to Google Drive.

        Returns:
            Tuple of (reel_path, manifest_path, drive_file_id, drive_link).
        """
        self.ready_dir.mkdir(parents=True, exist_ok=True)
        final_reel_path = self.ready_dir / f"reel_{date_str}.mp4"

        # Copy or move rendered reel to ready/reel_YYYY-MM-DD.mp4
        if reel_file_path != final_reel_path:
            final_reel_path.write_bytes(reel_file_path.read_bytes())

        # Ensure exactly 3 relevant hashtags
        chosen_hashtags = hashtags or ["#Quran", "#Islam", "#AyahOfTheDay"]
        if len(chosen_hashtags) > 3:
            chosen_hashtags = chosen_hashtags[:3]
        while len(chosen_hashtags) < 3:
            for fallback in ["#QuranRecitation", "#DailyAyah", "#IslamicReminder"]:
                if fallback not in chosen_hashtags:
                    chosen_hashtags.append(fallback)
                    if len(chosen_hashtags) == 3:
                        break

        # Sanitize strings to guarantee zero em-dash
        caption_clean = sanitize_no_em_dash(english_caption)
        ar_clean = sanitize_no_em_dash(arabic_text)
        ur_clean = sanitize_no_em_dash(urdu_translation)
        surah_en_clean = sanitize_no_em_dash(surah_name_english)

        # Upload to Google Drive if credentials exist
        drive_file_id: Optional[str] = None
        drive_link: Optional[str] = None

        try:
            logger.info(f"Uploading final reel to Google Drive ({final_reel_path.name})...")
            file_id, drive_path = self.uploader.upload_file(
                final_reel_path,
                custom_filename=final_reel_path.name,
                platform="islamic",
                mimetype="video/mp4",
                description=f"Quran Reel {date_str} - Surah {surah_en_clean} ({surah_number}:{ayah_number})",
            )
            drive_file_id = file_id
            drive_link = f"https://drive.google.com/file/d/{file_id}/view"
            logger.info(f"Google Drive upload successful! File ID: {drive_file_id}")
        except Exception as e:
            logger.warning(f"Google Drive upload notice: {e}")
            drive_file_id = None
            drive_link = None

        manifest = ReelManifest(
            reel_file=str(final_reel_path),
            date=date_str,
            surah_number=surah_number,
            ayah_number=ayah_number,
            ayah_end=ayah_end,
            surah_name_english=surah_en_clean,
            surah_name_arabic=surah_name_arabic,
            arabic_text=ar_clean,
            urdu_translation=ur_clean,
            caption=caption_clean,
            hashtags=chosen_hashtags,
            duration_seconds=round(duration_seconds, 2),
            drive_file_id=drive_file_id,
            drive_link=drive_link,
        )

        manifest.validate()

        manifest_path = self.ready_dir / "manifest.json"
        manifest_json_str = json.dumps(asdict(manifest), indent=2, ensure_ascii=False)
        manifest_path.write_text(manifest_json_str, encoding="utf-8")

        # Double check both files exist
        if not final_reel_path.exists() or final_reel_path.stat().st_size == 0:
            raise RuntimeError(f"Failed to generate {final_reel_path}")
        if not manifest_path.exists() or manifest_path.stat().st_size == 0:
            raise RuntimeError(f"Failed to generate {manifest_path}")

        logger.info(f"Successfully generated ready files:\n - {final_reel_path}\n - {manifest_path}")
        return final_reel_path, manifest_path, drive_file_id, drive_link
