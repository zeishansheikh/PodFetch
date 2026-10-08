"""
Main entrypoint and orchestration pipeline for YouTube Podcast to Google Drive automation.
Supports headless execution, CLI flags, safe crash recovery, and isolated error handling.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from config import AppConfig, load_config
from database import Database, VideoStatus
from discovery import ChannelDiscoverer, select_videos_for_run
from downloader import DownloadError, VideoDownloader
from drive_uploader import GoogleDriveAuthError, GoogleDriveUploadError, GoogleDriveUploader
from filename_utils import generate_video_filename
from filters import VideoCandidate
from logger import get_logger, log_automation_summary, setup_logger

logger = get_logger("main")


def print_database_status(db: Database) -> None:
    """Print comprehensive summary of current database contents and history."""
    stats = db.get_statistics()
    print("\n" + "=" * 50)
    print("YOUTUBE DRIVE AUTOMATION - SYSTEM STATUS")
    print("=" * 50)
    print(f"Total Video Records: {stats['total_records']}")
    print("-" * 50)
    print("Records by Status:")
    for status, count in sorted(stats["status_counts"].items()):
        print(f"  {status:<15}: {count}")

    if stats["channel_stats"]:
        print("-" * 50)
        print("Completed Uploads by Channel:")
        for row in stats["channel_stats"]:
            print(f"  {row['channel']:<30}: {row['uploaded']}")

    if stats["recent_failures"]:
        print("-" * 50)
        print("Recent Failures:")
        for fail in stats["recent_failures"]:
            print(f"  ID: {fail['youtube_video_id']} | Title: {fail['title']}")
            print(f"  Error: {fail['error_message']}")
            print(f"  Occurred: {fail['updated_at']}\n")
    print("=" * 50 + "\n")


def execute_pipeline(config: AppConfig, cli_channel: Optional[str] = None, cli_limit: Optional[int] = None) -> int:
    """Execute the end-to-end automation workflow.

    Returns:
        Exit code (0 for success, 1 if unhandled fatal error or failed videos).
    """
    logger.info("Starting YouTube to Google Drive automation run...")
    if config.dry_run:
        logger.info(">>> DRY RUN MODE ENABLED: No files will be downloaded or uploaded <<<")

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

    # 3. Channel Resolution & Discovery
    target_channels = [cli_channel] if cli_channel else config.youtube_channels
    discoverer = ChannelDiscoverer(config, db)
    downloader = VideoDownloader(config)

    logger.info(f"Checking {len(target_channels)} configured YouTube channel(s)...")
    eligible_by_channel, total_examined, total_skipped = discoverer.collect_and_filter_all_channels(
        channels=target_channels
    )

    total_eligible = sum(len(cands) for cands in eligible_by_channel.values())
    logger.info(f"Discovered {total_eligible} eligible candidate video(s) after filtering.")

    # 4. Fair Selection Strategy
    historical_counts = db.get_channel_selection_counts()
    selected_candidates: List[VideoCandidate] = select_videos_for_run(
        eligible_by_channel=eligible_by_channel,
        min_count=config.min_videos_per_run,
        max_count=config.max_videos_per_run,
        historical_counts=historical_counts,
        exact_limit=cli_limit,
    )

    logger.info(f"Selected {len(selected_candidates)} video(s) for this run.")
    for idx, cand in enumerate(selected_candidates, start=1):
        logger.info(
            f"  [{idx}] '{cand.title}' from '{cand.channel_name}' "
            f"({cand.duration_minutes:.1f}m) - {cand.youtube_url}"
        )

    downloaded_count = 0
    uploaded_count = 0
    failed_count = 0

    # 5. Process Selected Candidates
    for candidate in selected_candidates:
        video_id = candidate.youtube_video_id
        clean_filename = generate_video_filename(
            channel_name=candidate.channel_name,
            title=candidate.title,
            youtube_video_id=video_id,
            extension="mp4",
        )

        if config.dry_run:
            logger.info(
                f"[DRY RUN] Would download and upload: '{clean_filename}' "
                f"from {candidate.youtube_url}"
            )
            downloaded_count += 1
            uploaded_count += 1
            continue

        # Real Execution Flow
        downloaded_path: Optional[Path] = None
        try:
            # Step A: Ensure DB record exists and set status to DOWNLOADING
            db.upsert_video(
                youtube_video_id=video_id,
                title=candidate.title,
                youtube_url=candidate.youtube_url,
                channel_id=candidate.channel_id,
                channel_name=candidate.channel_name,
                published_at=candidate.published_at.isoformat() if candidate.published_at else None,
                duration=candidate.duration_seconds,
                status=VideoStatus.DOWNLOADING,
            )

            # Step B: Download
            logger.info(f"Downloading: '{candidate.title}' ({video_id})...")
            downloaded_path = downloader.download_video(candidate)
            downloaded_at = datetime.now(timezone.utc).isoformat()
            db.update_status(
                video_id,
                status=VideoStatus.DOWNLOADED,
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
                video_id,
                status=VideoStatus.UPLOADED,
                drive_file_id=drive_file_id,
                drive_path=drive_path,
                uploaded_at=uploaded_at,
            )
            uploaded_count += 1
            logger.info(
                f"Completed processing for '{candidate.title}' (Drive ID: {drive_file_id})"
            )

        except (DownloadError, GoogleDriveUploadError, Exception) as err:
            failed_count += 1
            error_msg = str(err)
            logger.error(
                f"Failed processing video '{candidate.title}' ({video_id}): {error_msg}",
                exc_info=True,
            )
            db.update_status(
                video_id,
                status=VideoStatus.FAILED,
                error_message=error_msg,
            )

        finally:
            # Step E: Delete temporary local file after upload attempt
            if downloaded_path and downloaded_path.exists():
                downloader.cleanup_file(downloaded_path)

    # 6. Generate and output final summary
    log_automation_summary(
        channels_checked=len(target_channels),
        new_candidates=total_eligible,
        selected=len(selected_candidates),
        downloaded=downloaded_count,
        uploaded=uploaded_count,
        skipped=total_skipped,
        failed=failed_count,
        logger=logger,
    )

    return 0 if failed_count == 0 else 1


def main() -> None:
    """CLI parser and orchestration runner."""
    parser = argparse.ArgumentParser(
        description="Headless automation for downloading YouTube podcast videos and uploading to Google Drive.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate channel discovery, filtering, and selection without downloading or uploading.",
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
        help="Target only a specific channel URL or handle for this run.",
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
    exit_code = execute_pipeline(config, cli_channel=args.channel, cli_limit=args.limit)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
