"""CLI entry point for the automated Quran ayah reel builder ("islamic" feature).
Implements the 11-step pipeline strictly in contract order per Contract Section 6:
python -m quran.build --date YYYY-MM-DD [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import load_config
from logger import get_logger
from quran.audio_cutter import cut_recitation_audio
from quran.background import BackgroundVideoManager
from quran.manifest import ManifestManager
from quran.playlist_fetcher import PlaylistFetcher
from quran.renderer import render_quran_reel, sanitize_no_em_dash
from quran.selector import select_best_ayah
from quran.state import ReelHistoryEntry, StateManager
from quran.tanzil import get_tanzil_db
from quran.transcribe import extract_audio_for_whisper, transcribe_audio

logger = get_logger("quran_build")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated Quran Ayah Reel Builder (PodFetch Islamic Feature)",
        prog="python -m quran.build",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Date for reel build in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run steps 1-5 (download, transcribe, select, Tanzil match) without video rendering",
    )
    parser.add_argument(
        "--playlist",
        type=str,
        default=None,
        help="Custom YouTube Quran recitation playlist URL",
    )
    parser.add_argument(
        "--video",
        type=str,
        default=None,
        help="Explicit single video URL for testing or dry-run",
    )
    return parser.parse_args()


def validate_date_format(date_str: str) -> str:
    """Validate that date strictly matches YYYY-MM-DD format."""
    pattern = r"^\d{4}-\d{2}-\d{2}$"
    if not re.match(pattern, date_str):
        raise ValueError(f"Invalid date format '{date_str}'. Must be YYYY-MM-DD.")
    return date_str


def run_pipeline(
    date_str: str,
    dry_run: bool = False,
    playlist_url: Optional[str] = None,
    override_video_url: Optional[str] = None,
) -> int:
    """Execute the automated Quran reel build pipeline strictly in contract order."""
    validate_date_format(date_str)
    current_step = "Step 0: Initialization"

    try:
        # -------------------------------------------------------------------
        # Step 1: State — read/write state.json per contract section 5
        # -------------------------------------------------------------------
        current_step = "Step 1: State initialization"
        logger.info(f"=== Starting Quran Reel Builder for Date {date_str} ===")
        logger.info(f"[{current_step}] Loading persistent state...")
        state_mgr = StateManager()
        tanzil_db = get_tanzil_db()
        logger.info(
            f"State loaded: next_index={state_mgr.state.next_index}, "
            f"{len(state_mgr.state.used_ayahs)} ayahs used, "
            f"{len(state_mgr.state.used_background_drive_ids)} backgrounds used."
        )

        # -------------------------------------------------------------------
        # Step 2: Just-in-time download — yt-dlp: download ONLY video at next_index
        # -------------------------------------------------------------------
        current_step = "Step 2: Just-in-time download"
        logger.info(f"[{current_step}] Fetching target video...")
        fetcher = PlaylistFetcher(state_mgr=state_mgr)
        video_path, video_meta = fetcher.download_next_video(
            playlist_url=playlist_url,
            override_video_url=override_video_url,
        )
        logger.info(f"Source video ready: {video_path.name} ('{video_meta.get('title')}')")

        # -------------------------------------------------------------------
        # Step 3: Transcription — extract audio, call Groq Whisper
        # -------------------------------------------------------------------
        current_step = "Step 3: Whisper transcription"
        logger.info(f"[{current_step}] Extracting audio and calling Groq Whisper...")
        audio_mp3_path = extract_audio_for_whisper(video_path)
        transcription = transcribe_audio(audio_mp3_path)
        if not transcription.segments:
            raise RuntimeError("Whisper returned empty transcript segments.")
        logger.info(f"Transcribed {len(transcription.segments)} segments successfully.")

        # -------------------------------------------------------------------
        # Step 4: Ayah selection — Groq LLM (openai/gpt-oss-20b)
        # -------------------------------------------------------------------
        current_step = "Step 4: Ayah selection with Groq LLM"
        logger.info(f"[{current_step}] Selecting standalone Ayah candidate...")
        selected_cand = select_best_ayah(
            transcription.segments,
            surah_name_hint=video_meta.get("title"),
        )
        logger.info(
            f"Selected candidate text: '{selected_cand.chosen_arabic}' "
            f"({selected_cand.start_time:.1f}s to {selected_cand.end_time:.1f}s, reason: {selected_cand.reason})"
        )

        # -------------------------------------------------------------------
        # Step 5: Ayah identification (accuracy-critical) — Tanzil fuzzy-match
        # -------------------------------------------------------------------
        current_step = "Step 5: Ayah identification with Tanzil"
        logger.info(f"[{current_step}] Matching Arabic against Tanzil Uthmani text...")
        match = tanzil_db.fuzzy_match(
            query_arabic=selected_cand.chosen_arabic,
            surah_hint=selected_cand.surah_hint,
            min_confidence=0.70,
        )

        if not match:
            raise RuntimeError(
                f"Tanzil fuzzy match failed for query '{selected_cand.chosen_arabic}'. Confidence below 0.70."
            )

        logger.info(
            f"Tanzil match resolved: Surah {match.surah_number}:{match.ayah_number} "
            f"({match.surah_name_english} / {match.surah_name_arabic}) with confidence {match.confidence:.3f}."
        )

        # Check for ayah reuse
        if state_mgr.is_ayah_used(match.surah_number, match.ayah_number):
            raise RuntimeError(
                f"Ayah {match.surah_number}:{match.ayah_number} was already used in a previous reel! (No-repeat rule)"
            )

        # In Dry-Run mode: print chosen ayah + timestamps + match confidence WITHOUT rendering
        if dry_run:
            logger.info("=== DRY-RUN / SELF-TEST RESULTS ===")
            print("\n" + "=" * 60)
            print("QURAN REEL BUILDER - DRY RUN SELF-TEST RESULTS")
            print("=" * 60)
            print(f"Date               : {date_str}")
            print(f"Playlist Video     : {video_meta.get('title')} ({video_meta.get('id')})")
            print(f"Surah              : {match.surah_number} - {match.surah_name_english} ({match.surah_name_arabic})")
            print(f"Ayah               : {match.ayah_number}" + (f"-{match.ayah_end}" if match.ayah_end else ""))
            print(f"Match Confidence   : {match.confidence * 100:.1f}%")
            print(f"Recitation Start   : {selected_cand.start_time:.2f}s")
            print(f"Translation End    : {selected_cand.end_time:.2f}s")
            print(f"Duration           : {selected_cand.duration:.2f}s")
            print(f"Selection Reason   : {selected_cand.reason}")
            print(f"English Caption    : {selected_cand.english_caption}")
            print(f"On-Screen Arabic   : {match.arabic_uthmani}")
            print(f"On-Screen Urdu     : {match.urdu_translation}")
            print("=" * 60 + "\n")
            logger.info("Dry-run completed successfully without video rendering.")
            return 0

        # -------------------------------------------------------------------
        # Step 6: Audio cut — ffmpeg: cut start-0.3s to end+0.3s, short fades
        # -------------------------------------------------------------------
        current_step = "Step 6: Audio precision cut"
        logger.info(f"[{current_step}] Cutting recitation audio with 0.3s fades and 8-40s sanity gating...")
        cut_audio_path, audio_dur = cut_recitation_audio(
            source_media_path=video_path,
            start_time=selected_cand.start_time,
            end_time=selected_cand.end_time,
        )
        logger.info(f"Trimmed audio created: {cut_audio_path.name} (duration: {audio_dur:.2f}s)")

        # -------------------------------------------------------------------
        # Step 7: Background video — reuse PodFetch Pinterest fetcher
        # -------------------------------------------------------------------
        current_step = "Step 7: Background video discovery and vetting"
        logger.info(f"[{current_step}] Sourcing vetted background video passing all locked gates...")
        bg_mgr = BackgroundVideoManager(state_mgr=state_mgr)
        bg_video_path, bg_pin = bg_mgr.fetch_vetted_background(target_duration=audio_dur)
        logger.info(f"Vetted background video ready: {bg_video_path.name} (Pin ID: {bg_pin.pin_id})")

        # -------------------------------------------------------------------
        # Step 8, 9, 10: Video prep, Text burn, and IG encode (1080x1920@60)
        # -------------------------------------------------------------------
        current_step = "Step 8-10: Video prep, Text burn, and Instagram encode"
        logger.info(f"[{current_step}] Rendering final reel with Noto Sans Arabic, Urdu, and 60fps encode...")
        temp_reel_path = video_path.parent / f"rendered_{date_str}.mp4"
        rendered_reel = render_quran_reel(
            background_video_path=bg_video_path,
            audio_path=cut_audio_path,
            duration_seconds=audio_dur,
            arabic_uthmani=match.arabic_uthmani,
            urdu_translation=match.urdu_translation,
            surah_number=match.surah_number,
            ayah_number=match.ayah_number,
            ayah_end=match.ayah_end,
            surah_name_english=match.surah_name_english,
            output_reel_path=temp_reel_path,
        )

        # -------------------------------------------------------------------
        # Step 11: Output — write ready/reel_YYYY-MM-DD.mp4 + ready/manifest.json
        # -------------------------------------------------------------------
        current_step = "Step 11: Manifest creation and Google Drive upload"
        logger.info(f"[{current_step}] Publishing ready files and syncing to Google Drive...")
        manifest_mgr = ManifestManager()
        final_reel, final_manifest, drive_id, drive_link = manifest_mgr.write_and_upload(
            date_str=date_str,
            reel_file_path=rendered_reel,
            surah_number=match.surah_number,
            ayah_number=match.ayah_number,
            ayah_end=match.ayah_end,
            surah_name_english=match.surah_name_english,
            surah_name_arabic=match.surah_name_arabic,
            arabic_text=match.arabic_uthmani,
            urdu_translation=match.urdu_translation,
            english_caption=selected_cand.english_caption,
            duration_seconds=audio_dur,
        )

        # Update state with successful history and advance playlist index
        state_mgr.add_history(
            ReelHistoryEntry(
                date=date_str,
                surah_number=match.surah_number,
                ayah_number=match.ayah_number,
                surah_name_english=match.surah_name_english,
                surah_name_arabic=match.surah_name_arabic,
                reel_path=str(final_reel),
                duration_seconds=audio_dur,
                drive_file_id=drive_id,
                drive_link=drive_link,
                playlist_video_id=video_meta.get("id"),
                playlist_index=video_meta.get("playlist_index"),
            )
        )
        if bg_pin and bg_pin.pin_id:
            state_mgr.mark_background_used(pin_id=bg_pin.pin_id, drive_id=drive_id)
        state_mgr.advance_index()

        # Final validation of ready/ deliverables per contract
        final_reel = Path(f"ready/reel_{date_str}.mp4")
        final_manifest = Path("ready/manifest.json")
        if not (final_reel.exists() and final_reel.stat().st_size > 0 and final_manifest.exists() and final_manifest.stat().st_size > 0):
            sys.stderr.write(f"ERROR: Build failed at [{current_step}]: ready files missing or empty\n")
            return 1

        logger.info(f"=== BUILD COMPLETED SUCCESSFULLY FOR {date_str} ===")
        print(f"SUCCESS: Built ready/reel_{date_str}.mp4 and ready/manifest.json")
        return 0

    except Exception as e:
        logger.error(f"Pipeline failed at [{current_step}]: {e}", exc_info=True)
        # Write NOTHING to ready/ on failure per contract hard rule
        try:
            Path(f"ready/reel_{date_str}.mp4").unlink(missing_ok=True)
            Path("ready/manifest.json").unlink(missing_ok=True)
        except Exception:
            pass
        sys.stderr.write(f"ERROR: Build failed at [{current_step}]: {e}\n")
        return 1


def main() -> None:
    args = parse_args()
    code = run_pipeline(
        date_str=args.date,
        dry_run=args.dry_run,
        playlist_url=args.playlist,
        override_video_url=args.video,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
