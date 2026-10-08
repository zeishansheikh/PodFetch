"""
Unit tests for filename sanitization and formatting utilities.
"""

from filename_utils import format_duration, generate_video_filename, sanitize_filename


def test_sanitize_filename_special_characters():
    raw = 'Lex Fridman: AI & Society? / "Future" <World> | Part*1'
    clean = sanitize_filename(raw)
    assert "/" not in clean
    assert "\\" not in clean
    assert ":" not in clean
    assert "*" not in clean
    assert "?" not in clean
    assert '"' not in clean
    assert "<" not in clean
    assert ">" not in clean
    assert "|" not in clean
    assert clean == "Lex Fridman_ AI & Society_Future_World_ Part_1"


def test_sanitize_filename_truncation():
    very_long_title = "A" * 300
    clean = sanitize_filename(very_long_title, max_length=50)
    assert len(clean) <= 50


def test_sanitize_filename_empty():
    assert sanitize_filename("") == "untitled"
    assert sanitize_filename("   ...   ") == "untitled"


def test_generate_video_filename():
    filename = generate_video_filename(
        channel_name="Huberman Lab",
        title="Master Your Sleep: Protocol & Tips",
        youtube_video_id="abc123XYZ00",
        extension="mp4",
    )
    assert filename == "Huberman Lab - Master Your Sleep_ Protocol & Tips - abc123XYZ00.mp4"
    assert filename.endswith(".mp4")


def test_format_duration():
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "01:01:05"
    assert format_duration(0) == "00:00"
    assert format_duration(None) == "Unknown"
