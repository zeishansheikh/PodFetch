"""
Unit tests for Pinterest discovery, filtering, parsing, and downloading.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from config import AppConfig
from database import Database
from filters import VideoCandidate, VideoFilter
from pinterest_discovery import (
    PinterestDiscoverer,
    PinterestPinMetadata,
    parse_pin_from_dict,
)
from pinterest_downloader import (
    PinterestDownloader,
    PinterestDownloadError,
    validate_media_with_ffprobe,
)


@pytest.fixture
def test_setup(tmp_path: Path):
    db_file = tmp_path / "test_pinterest.db"
    db = Database(db_file)
    config = AppConfig(
        database_path=db_file,
        pinterest_enabled=True,
        min_video_duration_seconds=10,
        max_video_duration_seconds=30,
        prefer_vertical=True,
        pinterest_keywords=["nature aesthetic 4k", "pink sunset aesthetic"],
    )
    v_filter = VideoFilter(config, db)
    return db, config, v_filter


def test_parse_pin_from_dict_video():
    """Verify video pin parsing extracts canonical URL, duration, width/height, and identifies video."""
    raw_pin = {
        "id": "100123456789",
        "title": "Aesthetic Waterfall",
        "description": "Dreamy waterfall in 4K",
        "link": "https://pinterest.com/pin/100123456789/",
        "media": {
            "media_type": "video",
            "duration": 18500,  # 18.5 seconds in ms
            "width": 1080,
            "height": 1920,
            "images": {
                "originals": {"url": "https://i.pinimg.com/originals/poster.jpg"}
            },
        },
        "videos": {
            "video_list": {
                "V_720P": {
                    "url": "https://v.pinimg.com/videos/waterfall_720p.mp4",
                    "width": 1080,
                    "height": 1920,
                    "duration": 18500,
                }
            }
        },
    }

    meta = parse_pin_from_dict(raw_pin, keyword="waterfall aesthetic")
    assert meta is not None
    assert meta.pin_id == "100123456789"
    assert meta.canonical_url == "https://www.pinterest.com/pin/100123456789/"
    assert meta.title == "Aesthetic Waterfall"
    assert meta.is_video is True
    assert meta.duration_seconds == 18
    assert meta.width == 1080
    assert meta.height == 1920
    assert meta.is_vertical is True

    cand = meta.to_video_candidate("waterfall aesthetic")
    assert cand.platform == "pinterest"
    assert cand.source_id == "100123456789"
    assert cand.is_image is False
    assert cand.is_vertical is True


def test_parse_pin_from_dict_static_image():
    """Verify static image pin is detected with is_video=False and converts to candidate with is_image=True."""
    raw_pin = {
        "id": "200987654321",
        "title": "Static Mountain Photo",
        "description": "Just a photo",
        "images": {
            "orig": {"url": "https://i.pinimg.com/originals/photo.jpg", "width": 800, "height": 600}
        },
    }

    meta = parse_pin_from_dict(raw_pin, keyword="mountain sunset aesthetic")
    assert meta is not None
    assert meta.pin_id == "200987654321"
    assert meta.is_video is False

    cand = meta.to_video_candidate("mountain sunset aesthetic")
    assert cand.platform == "pinterest"
    assert cand.source_id == "200987654321"
    assert cand.is_image is True


def test_parse_pin_from_dict_missing_metadata():
    """Verify pin with missing metadata does not invent values and handles unknowns safely."""
    raw_pin = {
        "id": "300111222333",
        # missing title, description, duration, width/height
    }

    meta = parse_pin_from_dict(raw_pin, keyword="unknown clip")
    assert meta is not None
    assert meta.pin_id == "300111222333"
    assert "300111222333" in meta.title
    assert meta.duration_seconds is None
    assert meta.width is None
    assert meta.height is None
    assert meta.is_vertical is None

    cand = meta.to_video_candidate("unknown clip")
    assert cand.platform == "pinterest"
    assert cand.duration_seconds is None
    assert cand.is_vertical is None


def test_pinterest_filter_evaluation(test_setup):
    """Verify video filtering against duration constraints and image exclusion."""
    _, _, v_filter = test_setup

    # Valid video (18 seconds, within 10-30s range)
    valid_cand = VideoCandidate(
        youtube_video_id="pin_v1",
        channel_id="pinterest",
        channel_name="Pinterest",
        title="Valid Sunset Clip",
        youtube_url="https://www.pinterest.com/pin/pin_v1/",
        duration_seconds=18,
        platform="pinterest",
        source_id="pin_v1",
        is_image=False,
    )
    is_valid, reason = v_filter.evaluate_candidate(valid_cand)
    assert is_valid, f"Should be valid: {reason}"

    # Static image rejected
    image_cand = VideoCandidate(
        youtube_video_id="pin_img",
        channel_id="pinterest",
        channel_name="Pinterest",
        title="Image Pin",
        youtube_url="https://www.pinterest.com/pin/pin_img/",
        platform="pinterest",
        source_id="pin_img",
        is_image=True,
    )
    is_valid, reason = v_filter.evaluate_candidate(image_cand)
    assert not is_valid
    assert "Static image" in reason

    # Too short (< 10s)
    short_cand = VideoCandidate(
        youtube_video_id="pin_short",
        channel_id="pinterest",
        channel_name="Pinterest",
        title="Too short clip",
        youtube_url="https://www.pinterest.com/pin/pin_short/",
        duration_seconds=5,
        platform="pinterest",
        source_id="pin_short",
        is_image=False,
    )
    is_valid, reason = v_filter.evaluate_candidate(short_cand)
    assert not is_valid
    assert "less than Pinterest minimum required 10s" in reason

    # Too long (> 30s)
    long_cand = VideoCandidate(
        youtube_video_id="pin_long",
        channel_id="pinterest",
        channel_name="Pinterest",
        title="Too long clip",
        youtube_url="https://www.pinterest.com/pin/pin_long/",
        duration_seconds=45,
        platform="pinterest",
        source_id="pin_long",
        is_image=False,
    )
    is_valid, reason = v_filter.evaluate_candidate(long_cand)
    assert not is_valid
    assert "exceeds Pinterest maximum limit of 30s" in reason

    # Unknown duration allowed when metadata missing
    unknown_duration_cand = VideoCandidate(
        youtube_video_id="pin_unknown",
        channel_id="pinterest",
        channel_name="Pinterest",
        title="Unknown Duration Clip",
        youtube_url="https://www.pinterest.com/pin/pin_unknown/",
        duration_seconds=None,
        platform="pinterest",
        source_id="pin_unknown",
        is_image=False,
    )
    is_valid, _ = v_filter.evaluate_candidate(unknown_duration_cand)
    assert is_valid


def test_pinterest_discoverer_deduplication_and_multiple_keywords(test_setup):
    """Verify deduplication when multiple keywords return the same Pin ID."""
    db, config, _ = test_setup
    discoverer = PinterestDiscoverer(config, db)

    # Pin P1 found in keyword 1 AND keyword 2
    pin_p1_kw1 = PinterestPinMetadata(
        pin_id="P1",
        canonical_url="https://www.pinterest.com/pin/P1/",
        title="Golden Hour River",
        is_video=True,
        duration_seconds=20,
        width=1080,
        height=1920,
        discovered_keywords=["golden hour nature"],
    )
    pin_p1_kw2 = PinterestPinMetadata(
        pin_id="P1",
        canonical_url="https://www.pinterest.com/pin/P1/",
        title="Golden Hour River",
        is_video=True,
        duration_seconds=20,
        width=1080,
        height=1920,
        discovered_keywords=["river flowing nature aesthetic"],
    )
    pin_p2_kw2 = PinterestPinMetadata(
        pin_id="P2",
        canonical_url="https://www.pinterest.com/pin/P2/",
        title="Forest Path",
        is_video=True,
        duration_seconds=15,
        width=1080,
        height=1920,
        discovered_keywords=["forest road aesthetic"],
    )

    def fake_search(keyword: str):
        if "golden hour" in keyword:
            return [pin_p1_kw1]
        elif "river" in keyword:
            return [pin_p1_kw2, pin_p2_kw2]
        return []

    with patch.object(discoverer, "search_keyword", side_effect=fake_search):
        eligible, total_found, skipped, errors = discoverer.discover_all_keywords(
            keywords=["golden hour nature", "river flowing nature aesthetic"]
        )

        assert total_found == 3
        # P1 was discovered twice, so eligible should have 2 unique pins
        assert len(eligible) == 2
        p1 = next(c for c in eligible if c.source_id == "P1")
        # Ensure keywords are merged
        assert "golden hour nature" in p1.search_keyword
        assert "river flowing nature aesthetic" in p1.search_keyword


def test_pinterest_discoverer_isolated_keyword_failure(test_setup):
    """Verify that an exception on one keyword does not stop discovery of subsequent keywords."""
    db, config, _ = test_setup
    discoverer = PinterestDiscoverer(config, db)

    pin_good = PinterestPinMetadata(
        pin_id="P_good",
        canonical_url="https://www.pinterest.com/pin/P_good/",
        title="Good Pin",
        is_video=True,
        duration_seconds=15,
        width=1080,
        height=1920,
        discovered_keywords=["healthy_keyword"],
    )

    def side_effect_search(keyword: str):
        if keyword == "failing_keyword":
            raise RuntimeError("Network glitch on search")
        return [pin_good]

    with patch.object(discoverer, "search_keyword", side_effect=side_effect_search):
        eligible, total_found, _, errors = discoverer.discover_all_keywords(
            keywords=["failing_keyword", "healthy_keyword"]
        )
        assert len(eligible) == 1
        assert eligible[0].source_id == "P_good"
        assert len(errors) == 1
        assert "failing_keyword" in errors[0]


def test_ffprobe_media_validation(tmp_path: Path):
    """Verify FFprobe validation checks video stream existence and rejects audio-only or empty files."""
    dummy_file = tmp_path / "test.mp4"
    dummy_file.write_bytes(b"x" * (100 * 1024))

    # Valid video probe result
    valid_probe_json = (
        '{"streams": [{"codec_type": "video", "width": 1080, "height": 1920, "codec_name": "h264"}],'
        ' "format": {"duration": "15.5", "size": "1048576", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"}}'
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=valid_probe_json)
        is_valid, err_msg, meta = validate_media_with_ffprobe(dummy_file)
        assert is_valid is True
        assert err_msg is None
        assert meta.get("width") == 1080
        assert meta.get("height") == 1920

    # Probe result with NO video streams
    no_video_probe_json = (
        '{"streams": [{"codec_type": "audio"}],'
        ' "format": {"duration": "10.0", "size": "50000", "format_name": "mp3"}}'
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=no_video_probe_json)
        is_valid, err_msg, meta = validate_media_with_ffprobe(dummy_file)
        assert is_valid is False
        assert "could not identify a valid video codec" in err_msg


def test_pinterest_downloader_retry_backoff(tmp_path: Path):
    """Verify bounded exponential backoff retries transient failures."""
    config = AppConfig(
        temp_dir=tmp_path / "temp",
        max_retries=2,
        backoff_factor=1.5,
    )
    config.temp_dir.mkdir(parents=True, exist_ok=True)
    downloader = PinterestDownloader(config)

    cand = VideoCandidate(
        youtube_video_id="P_fail",
        channel_id="pinterest",
        channel_name="Pinterest",
        title="Failing Pin",
        youtube_url="https://www.pinterest.com/pin/P_fail/",
        platform="pinterest",
        source_id="P_fail",
    )

    # Force download to fail consistently and test retry backoff
    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls, patch("time.sleep") as mock_sleep:
        mock_ydl = MagicMock()
        mock_ydl.download.side_effect = RuntimeError("Simulated network timeout")
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        with pytest.raises(PinterestDownloadError) as exc_info:
            downloader.download_video(cand)

        assert "Failed to download Pinterest video" in str(exc_info.value)
        # Should have retried max_retries times
        assert mock_ydl.download.call_count == 2
        mock_sleep.assert_called_once()
