"""
Centralized logging configuration for YouTube to Google Drive Automation.
Provides structured console output and rotating file logging.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logger(
    log_dir: str | Path = "logs",
    log_file: str = "automation.log",
    level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """Configure and return the root project logger.

    Args:
        log_dir: Directory where log files are stored.
        log_file: Name of the log file.
        level: Logging level (e.g. logging.INFO, logging.DEBUG).
        max_bytes: Maximum size of a log file before rotation.
        backup_count: Number of rotated log files to retain.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("yt_drive_automation")
    logger.setLevel(level)

    # Avoid duplicate handlers if setup_logger is invoked multiple times
    if logger.handlers:
        return logger

    # Ensure log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    full_log_file = log_path / log_file

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler (Stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Rotating File Handler
    file_handler = RotatingFileHandler(
        filename=full_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Retrieve child logger with consistent prefix."""
    if name:
        return logging.getLogger(f"yt_drive_automation.{name}")
    return logging.getLogger("yt_drive_automation")


def log_podfetch_summary(
    youtube_candidates: int,
    pinterest_candidates: int,
    duplicates_skipped: int,
    eligible_videos: int,
    selected: int,
    downloaded: int,
    uploaded: int,
    failed: int,
    instagram_candidates: int = 0,
    limitations: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Output the exact PODFETCH SUMMARY execution report format specified in requirements."""
    active_logger = logger or get_logger()
    summary_lines = [
        "",
        "PODFETCH SUMMARY",
        "",
        f"YouTube candidates: {youtube_candidates}",
        f"Pinterest candidates: {pinterest_candidates}",
        f"Instagram audio candidates: {instagram_candidates}",
        f"Duplicates skipped: {duplicates_skipped}",
        f"Eligible items: {eligible_videos}",
        f"Selected: {selected}",
        f"Downloaded: {downloaded}",
        f"Uploaded to Google Drive: {uploaded}",
        f"Failed: {failed}",
    ]
    if limitations:
        summary_lines.append("")
        summary_lines.append("API Limitations / Notices:")
        for lim in limitations:
            summary_lines.append(f"  - {lim}")
    summary_lines.append("")

    summary_text = "\n".join(summary_lines)
    for line in summary_lines:
        if line.strip():
            active_logger.info(line)
    print(summary_text, flush=True)


def log_automation_summary(
    channels_checked: int = 0,
    new_candidates: int = 0,
    selected: int = 0,
    downloaded: int = 0,
    uploaded: int = 0,
    skipped: int = 0,
    failed: int = 0,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Output execution summary banner for backwards compatibility."""
    active_logger = logger or get_logger()
    summary_lines = [
        "",
        "========================================",
        "AUTOMATION COMPLETE",
        "========================================",
        f"Channels checked: {channels_checked}",
        f"New candidates:   {new_candidates}",
        f"Selected:         {selected}",
        f"Downloaded:       {downloaded}",
        f"Uploaded:         {uploaded}",
        f"Skipped:          {skipped}",
        f"Failed:           {failed}",
        "========================================",
        "",
    ]
    summary_text = "\n".join(summary_lines)
    for line in summary_lines:
        if line.strip():
            active_logger.info(line)
    print(summary_text, flush=True)

