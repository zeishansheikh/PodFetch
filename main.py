"""
Main entrypoint and orchestration pipeline for YouTube and Pinterest to Google Drive automation.
Supports headless execution, CLI flags, safe crash recovery, isolated error handling,
and balanced multi-source selection.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config import AppConfig, load_config
from database import Database, VideoStatus
from discovery import ChannelDiscoverer, select_multisource_candidates, select_videos_for_run
from downloader import DownloadError, VideoDownloader
from drive_uploader import GoogleDriveAuthError, GoogleDriveUploadError, GoogleDriveUploader
from filename_utils import generate_source_filename, generate_video_filename
from filters import VideoCandidate, VideoFilter
from logger import get_logger, log_podfetch_summary, setup_logger
from pinterest_discovery import PinterestDiscoverer
from pinterest_downloader import PinterestDownloader, PinterestDownloadError

logger = get_logger("main")


def print_database_status(db: Database) -> None:
    """Print comprehensive summary of current database contents and history."""
    stats = db.get_statistics()
    print("\n" + "=" * 50)
    print("PODFETCH AUTOMATION - SYSTEM STATUS")
    print("=" * 50)
    print(f"Total Video Records: {stats['total_records']}")
    print("-" * 50)
    print("Records by Status:")
    for status, count in sorted(stats["status_counts"].items()):
        print(f"  {status:<15}: {count}")

    if stats.get("platform_counts"):
        print("-" * 50)
        print("Records by Platform:")
        for plat, count in sorted(stats["platform_counts"].items()):
            print(f"  {plat:<15}: {count}")

    if stats["channel_stats"]:
        print("-" * 50)
        print("Completed Uploads by Source/Channel:")
        for row in stats["channel_stats"]:
            print(f"  [{row.get('platform', 'unknown')}] {row['channel']:<28}: {row['uploaded']}")

    if stats["recent_failures"]:
        print("-" * 50)
        print("Recent Failures:")
        for fail in stats["recent_failures"]:
            src_id = fail.get("source_id") or fail.get("youtube_video_id")
            plat = fail.get("platform", "unknown")
            print(f"  [{plat}] ID: {src_id} | Title: {fail['title']}")
            print(f"  Error: {fail['error_message']}")
            print(f"  Occurred: {fail['updated_at']}\n")
    print("=" * 50 + "\n")


def execute_pipeline(
    config: AppConfig,
    cli_channel: Optional[str] = None,
    cli_limit: Optional[int] = None,
    cli_source: Optional[str] = None,
) -> int:
    """Execute the end-to-end automation workflow across enabled sources.

    Returns:
        Exit code (0 for success, 1 if unhandled fatal error or failed videos).
    """
    logger.info("Starting PodFetch YouTube + Pinterest to Google Drive automation run...")
    if config.dry_run:
        logger.info(">>> DRY RUN MODE ENABLED: No files will be downloaded or uploaded <<<")

    # Determine active sources
    if cli_source == "youtube":
        active_sources = ["youtube"]
    elif cli_source == "pinterest":
        active_sources = ["pinterest"]
    elif cli_source == "all":
        active_sources = ["youtube", "pinterest"]
    else:
        active_sources = [s for s in config.enabled_sources if s in ("youtube", "pinterest")]

    logger.info(f"Active sources for this run: {', '.join(active_sources)}")

    # 1. Initialize Database & Safe Resume Recovery
    db = Database(config.database_path)
    recovery_stats = db.recover_interrupted_states(config.temp_dir)
    if recovery_stats.get("reset_from_downloading", 0) > 0:
        logger.info(
            f"Recovered {recovery_stats['reset_from_downloading']} interrupted "
            "video(s) from prior abnormal shutdown."
        )

    # 2. Check & Pre-authenticate Google Drive (if not dry run)
    drive_uploader: Optional[GoogleDriveUploader] = None
    if not config.dry_run:
        try:
            drive_uploader = GoogleDriveUploader(config)
            drive_uploader.authenticate()
        except GoogleDriveAuthError as err:
            logger.error(f"Google Drive authentication failed: {err}")
            return 1
        except Exception as err:
            logger.error(f"Unexpected error initializing Google Drive: {err}", exc_info=True)
            return 1

    # 3. Discovery across enabled sources
    video_filter = VideoFilter(config, db)
    candidates_by_source: Dict[str, List[VideoCandidate]] = {"youtube": [], "pinterest": []}
    youtube_examined = 0
    pinterest_examined = 0
    total_skipped = 0

    # Source 1: YouTube Discovery
    if "youtube" in active_sources:
        try:
            target_channels = [cli_channel] if cli_channel else config.youtube_channels
            discoverer = ChannelDiscoverer(config, db)
            logger.info(f"Checking {len(target_channels)} configured YouTube channel(s)...")
            eligible_by_channel, yt_examined, yt_skipped = discoverer.collect_and_filter_all_channels(
                channels=target_channels
            )
            youtube_examined = yt_examined
            total_skipped += yt_skipped
            all_yt_eligible = [c for cands in eligible_by_channel.values() for c in cands]
            candidates_by_source["youtube"] = all_yt_eligible
            logger.info(f"Discovered {len(all_yt_eligible)} eligible YouTube candidate(s).")
        except Exception as yt_err:
            logger.error(f"YouTube discovery failed (continuing with other sources): {yt_err}", exc_info=True)

    # Source 2: Pinterest Discovery
    if "pinterest" in active_sources:
        try:
            pin_discoverer = PinterestDiscoverer(config, db)
            pin_candidates, pin_examined, pin_skipped, pin_errors = pin_discoverer.discover_all_keywords()
            pinterest_examined = pin_examined
            total_skipped += pin_skipped

            # Filter candidates against database and duration rules
            accepted_pins, rejected_pins = video_filter.filter_candidates(pin_candidates)
            total_skipped += len(rejected_pins)
            candidates_by_source["pinterest"] = accepted_pins
            logger.info(f"Discovered {len(accepted_pins)} eligible Pinterest candidate(s).")

            # Register eligible Pinterest candidates as DISCOVERED in DB
            if not config.dry_run:
                for pc in accepted_pins:
                    db.upsert_video(
                        source_id=pc.source_id,
                        title=pc.title,
                        canonical_url=pc.canonical_url,
                        platform="pinterest",
                        search_keyword=pc.search_keyword,
                        duration=pc.duration_seconds,
                        status=VideoStatus.DISCOVERED,
                    )
        except Exception as pin_err:
            logger.error(f"Pinterest discovery failed (continuing with other sources): {pin_err}", exc_info=True)

    total_eligible = sum(len(cands) for cands in candidates_by_source.values())
    logger.info(f"Total eligible candidate video(s) across all sources: {total_eligible}")

    # 4. Multi-Source Fair & Balanced Selection
    historical_counts = db.get_channel_selection_counts()
    selected_candidates: List[VideoCandidate] = select_multisource_candidates(
        candidates_by_source=candidates_by_source,
        min_count=config.min_videos_per_run,
        max_count=config.max_videos_per_run,
        historical_counts=historical_counts,
        exact_limit=cli_limit,
        prefer_vertical=config.prefer_vertical,
    )

    logger.info(f"Selected {len(selected_candidates)} video(s) for this run.")
    for idx, cand in enumerate(selected_candidates, start=1):
        dur_str = f"{cand.duration_seconds}s" if cand.duration_seconds else "Unknown dur"
        logger.info(
            f"  [{idx}] [{cand.platform.upper()}] '{cand.title}' "
            f"({dur_str}) - {cand.canonical_url}"
        )

    downloaded_count = 0
    uploaded_count = 0
    failed_count = 0

    # Initialize downloaders
    youtube_downloader = VideoDownloader(config)
    pinterest_downloader = PinterestDownloader(config)

    # 5. Process Selected Candidates
    for candidate in selected_candidates:
        platform = candidate.platform
        source_id = candidate.source_id or candidate.youtube_video_id
        keyword_or_channel = candidate.search_keyword or candidate.channel_name

        clean_filename = generate_source_filename(
            platform=platform,
            keyword_or_channel=keyword_or_channel,
            source_id=source_id,
            extension="mp4",
        )

        if config.dry_run:
            logger.info(
                f"[DRY RUN] Would download and upload: '{clean_filename}' "
                f"from {candidate.canonical_url}"
            )
            downloaded_count += 1
            uploaded_count += 1
            continue

        # Real Execution Flow
        downloaded_path: Optional[Path] = None
        downloader_in_use = (
            pinterest_downloader if platform == "pinterest" else youtube_downloader
        )

        try:
            # Step A: Update status to DOWNLOADING
            db.upsert_video(
                source_id=source_id,
                title=candidate.title,
                canonical_url=candidate.canonical_url,
                platform=platform,
                youtube_video_id=candidate.youtube_video_id if platform == "youtube" else None,
                channel_id=candidate.channel_id,
                channel_name=candidate.channel_name,
                youtube_url=candidate.youtube_url if platform == "youtube" else None,
                search_keyword=candidate.search_keyword,
                published_at=candidate.published_at.isoformat() if candidate.published_at else None,
                duration=candidate.duration_seconds,
                status=VideoStatus.DOWNLOADING,
            )

            # Step B: Download video
            logger.info(f"Downloading [{platform.upper()}]: '{candidate.title}' ({source_id})...")
            downloaded_path = downloader_in_use.download_video(candidate)
            downloaded_at = datetime.now(timezone.utc).isoformat()

            db.update_status(
                source_id=source_id,
                status=VideoStatus.DOWNLOADED,
                platform=platform,
                downloaded_at=downloaded_at,
            )
            downloaded_count += 1

            # Step C: Upload to Google Drive
            assert drive_uploader is not None
            logger.info(f"Uploading to Google Drive: '{downloaded_path.name}'...")
            drive_file_id, drive_path = drive_uploader.upload_video(
                downloaded_path, custom_filename=clean_filename
            )
            uploaded_at = datetime.now(timezone.utc).isoformat()

            # Step D: Update DB status to UPLOADED
            db.update_status(
                source_id=source_id,
                status=VideoStatus.UPLOADED,
                platform=platform,
                drive_file_id=drive_file_id,
                drive_path=drive_path,
                uploaded_at=uploaded_at,
            )
            uploaded_count += 1
            logger.info(
                f"Completed processing for '{candidate.title}' (Drive ID: {drive_file_id})"
            )

        except (DownloadError, PinterestDownloadError, GoogleDriveUploadError, Exception) as err:
            failed_count += 1
            error_msg = str(err)
            logger.error(
                f"Failed processing [{platform}] video '{candidate.title}' ({source_id}): {error_msg}",
                exc_info=True,
            )
            db.update_status(
                source_id=source_id,
                status=VideoStatus.FAILED,
                platform=platform,
                error_message=error_msg,
            )

        finally:
            # Step E: Delete temporary local file after upload attempt
            if downloaded_path and downloaded_path.exists():
                downloader_in_use.cleanup_file(downloaded_path)

    # 6. Output final PODFETCH SUMMARY report
    log_podfetch_summary(
        youtube_candidates=youtube_examined,
        pinterest_candidates=pinterest_examined,
        duplicates_skipped=total_skipped,
        eligible_videos=total_eligible,
        selected=len(selected_candidates),
        downloaded=downloaded_count,
        uploaded=uploaded_count,
        failed=failed_count,
        logger=logger,
    )

    return 0 if failed_count == 0 else 1


def main() -> None:
    """CLI parser and orchestration runner."""
    parser = argparse.ArgumentParser(
        description="Headless automation for discovering and downloading YouTube & Pinterest videos and uploading to Google Drive.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate discovery, filtering, and selection without downloading or uploading.",
    )
    parser.add_argument(
        "--source",
        type=str,
        choices=["youtube", "pinterest", "all"],
        default=None,
        help="Specify source to run: 'youtube', 'pinterest', or 'all' (default: uses configured ENABLED_SOURCES).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override video count limit for this run (e.g. --limit 1 or --limit 3).",
    )
    parser.add_argument(
        "--channel",
        type=str,
        default=None,
        help="Target only a specific YouTube channel URL or handle for this run.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show database processing statistics, channel counts, and recent failures.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Reset all FAILED videos in the database back to DISCOVERED so they can be retried.",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=None,
        help="Path to custom .env file.",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(env_file=args.env_file)

    # Apply CLI flag overrides
    if args.dry_run:
        config.dry_run = True
    if args.channel:
        config.youtube_channels = [args.channel]
    if args.limit:
        config.min_videos_per_run = min(config.min_videos_per_run, args.limit)
        config.max_videos_per_run = args.limit
    if args.source:
        if args.source == "youtube":
            config.enabled_sources = ["youtube"]
            config.youtube_enabled = True
            config.pinterest_enabled = False
        elif args.source == "pinterest":
            config.enabled_sources = ["pinterest"]
            config.youtube_enabled = False
            config.pinterest_enabled = True
        elif args.source == "all":
            config.enabled_sources = ["youtube", "pinterest"]
            config.youtube_enabled = True
            config.pinterest_enabled = True

    # Setup project logger
    setup_logger(log_dir=config.log_dir)

    # Handle --status command
    if args.status:
        db = Database(config.database_path)
        print_database_status(db)
        sys.exit(0)

    # Handle --retry-failed command
    if args.retry_failed:
        db = Database(config.database_path)
        reset_count = db.retry_failed_videos()
        print(f"Reset {reset_count} failed video(s) to DISCOVERED.")
        logger.info(f"Reset {reset_count} failed video(s) to DISCOVERED.")
        sys.exit(0)

    # Validate configuration for execution
    try:
        config.validate(is_status_command=False)
    except ValueError as val_err:
        logger.error(f"Configuration Error: {val_err}")
        print(f"\n[ERROR] Configuration Error: {val_err}\n", file=sys.stderr)
        sys.exit(1)

    # Execute workflow
    exit_code = execute_pipeline(
        config,
        cli_channel=args.channel,
        cli_limit=args.limit,
        cli_source=args.source,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

