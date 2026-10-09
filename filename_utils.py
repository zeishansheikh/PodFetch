"""
Filename and text utility functions for filesystem and metadata safety.
"""

from __future__ import annotations

import re
import unicodedata


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Sanitize string to create a safe filename across Windows, macOS, and Linux.

    Args:
        name: Raw string (e.g. video title, channel name).
        max_length: Maximum allowed characters for the sanitized string.

    Returns:
        Filesystem-safe string.
    """
    if not name:
        return "untitled"

    # Normalize unicode characters
    normalized = unicodedata.normalize("NFKD", name)

    # Replace illegal filesystem characters: / \ : * ? " < > | \0
    clean = re.sub(r'[\\/*?:"<>|\x00]', "_", normalized)

    # Collapse whitespace and repeated underscores
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"_+", "_", clean)
    clean = re.sub(r"(?:_\s*)+_", "_", clean)

    # Strip leading/trailing dots, underscores and spaces
    clean = clean.strip(". _")

    if not clean:
        clean = "untitled"

    # Limit length safely
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip(". ")

    return clean


def generate_video_filename(
    channel_name: str,
    title: str,
    youtube_video_id: str,
    extension: str = "mp4",
) -> str:
    """Generate standardized, unique filename for downloaded podcast videos.

    Format:
        {channel_name} - {title} - {youtube_video_id}.mp4

    Args:
        channel_name: Name of the YouTube channel.
        title: Title of the video.
        youtube_video_id: 11-character YouTube video ID.
        extension: File extension without leading dot (default 'mp4').

    Returns:
        Formatted and sanitized filename.
    """
    clean_channel = sanitize_filename(channel_name, max_length=40)
    clean_title = sanitize_filename(title, max_length=120)
    clean_video_id = sanitize_filename(youtube_video_id, max_length=30)
    clean_ext = extension.lstrip(".")

    return f"{clean_channel} - {clean_title} - {clean_video_id}.{clean_ext}"


def generate_source_filename(
    platform: str,
    keyword_or_channel: str,
    source_id: str,
    extension: str = "mp4",
) -> str:
    """Generate standardized filename for Pinterest or YouTube source candidates.

    Format:
        {Platform} - {keyword_or_channel} - {source_id}.mp4
        Example:
            Pinterest - aesthetic-nature-videos - 123456789.mp4
            YouTube - nature-aesthetic - abc123XYZ00.mp4

    Args:
        platform: Source platform name ('Pinterest', 'YouTube', etc.).
        keyword_or_channel: The search keyword or channel name.
        source_id: Platform-specific unique ID (Pin ID or YouTube video ID).
        extension: File extension without leading dot (default 'mp4').

    Returns:
        Formatted and sanitized filename.
    """
    clean_platform = sanitize_filename(platform.capitalize(), max_length=20)
    # Replace spaces with hyphens for clean slug-like keyword representation if preferred
    clean_keyword = sanitize_filename(keyword_or_channel.replace(" ", "-"), max_length=60)
    clean_id = sanitize_filename(source_id, max_length=40)
    clean_ext = extension.lstrip(".")

    return f"{clean_platform} - {clean_keyword} - {clean_id}.{clean_ext}"


def format_duration(seconds: int | float | None) -> str:
    """Format duration in seconds to human-readable string (e.g., '01:25:30' or '45:10')."""
    if seconds is None or seconds < 0:
        return "Unknown"

    total_secs = int(seconds)
    hours = total_secs // 3600
    minutes = (total_secs % 3600) // 60
    secs = total_secs % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

