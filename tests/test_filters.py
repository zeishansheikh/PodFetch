"""
Unit tests for video filtering logic.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from config import AppConfig
from database import Database, VideoStatus
from filters import VideoCandidate, VideoFilter


@pytest.fixture
def test_setup(tmp_path: Path):
    db_file = tmp_path / "filter_test.db"
    db = Database(db_file)
    config = AppConfig(
        min_duration_minutes=20,
        max_video_age_days=30,
        allow_shorts=False,
        allow_livestreams=False,
    )
    video_filter = VideoFilter(config, db)
    return db, config, video_filter


def test_reject_short_video(test_setup):
    _, _, v_filter = test_setup
    cand = VideoCandidate(
        youtube_video_id="short1",
        channel_id="ch1",
        channel_name="Huberman Lab",
        title="Quick Tip",
        youtube_url="https://youtube.com/shorts/short1",
        duration_seconds=50,
        is_short=True,
    )
    is_valid, reason = v_filter.evaluate_candidate(cand)
    assert not is_valid
    assert "Short" in reason


def test_reject_short_duration_under_20_minutes(test_setup):
    _, _, v_filter = test_setup
    cand = VideoCandidate(
        youtube_video_id="clip1",
        channel_id="ch1",
        channel_name="Huberman Lab",
        title="15-minute clip",
        youtube_url="https://youtube.com/watch?v=clip1",
        duration_seconds=15 * 60,  # 15 minutes
    )
    is_valid, reason = v_filter.evaluate_candidate(cand)
    assert not is_valid
    assert "less than minimum required 20m" in reason


def test_accept_full_length_podcast(test_setup):
    _, _, v_filter = test_setup
    now = datetime.now(timezone.utc)
    cand = VideoCandidate(
        youtube_video_id="full_ep",
        channel_id="ch1",
        channel_name="Huberman Lab",
        title="Full Episode #150: Neuroscience and Focus",
        youtube_url="https://youtube.com/watch?v=full_ep",
        published_at=now - timedelta(days=5),
        duration_seconds=125 * 60,  # 2 hours 5 mins
    )
    is_valid, reason = v_filter.evaluate_candidate(cand)
    assert is_valid
    assert reason is None


def test_reject_outdated_video(test_setup):
    _, _, v_filter = test_setup
    old_date = datetime.now(timezone.utc) - timedelta(days=45)
    cand = VideoCandidate(
        youtube_video_id="old_ep",
        channel_id="ch1",
        channel_name="Huberman Lab",
        title="Old Episode",
        youtube_url="https://youtube.com/watch?v=old_ep",
        published_at=old_date,
        duration_seconds=60 * 60,
    )
    is_valid, reason = v_filter.evaluate_candidate(cand)
    assert not is_valid
    assert "exceeding 30 days limit" in reason


def test_reject_already_uploaded_video(test_setup):
    db, _, v_filter = test_setup
    db.upsert_video(
        youtube_video_id="already_done",
        title="Past Episode",
        youtube_url="https://youtube.com/watch?v=already_done",
        status=VideoStatus.UPLOADED,
    )
    cand = VideoCandidate(
        youtube_video_id="already_done",
        channel_id="ch1",
        channel_name="Huberman Lab",
        title="Past Episode",
        youtube_url="https://youtube.com/watch?v=already_done",
        duration_seconds=45 * 60,
    )
    is_valid, reason = v_filter.evaluate_candidate(cand)
    assert not is_valid
    assert "Already processed" in reason


def test_reject_low_resolution_pinterest_video(test_setup):
    """Verify that lower-resolution videos (like 360p or 624x1032) are rejected under 1080p rule."""
    _, config, v_filter = test_setup
    config.min_video_resolution = 1080

    low_res_cand = VideoCandidate(
        youtube_video_id="pin_low_res",
        channel_id="pinterest_nature",
        channel_name="Pinterest",
        title="Low Quality Clip",
        youtube_url="https://pinterest.com/pin/pin_low_res",
        platform="pinterest",
        source_id="pin_low_res",
        duration_seconds=15,
        width=624,
        height=1032,
    )
    is_valid, reason = v_filter.evaluate_candidate(low_res_cand)
    assert not is_valid
    assert "lower than required 1080p" in reason


def test_accept_1080p_pinterest_video(test_setup):
    """Verify that genuine 1080x1920 vertical videos are accepted."""
    _, config, v_filter = test_setup
    config.min_video_resolution = 1080

    hd_cand = VideoCandidate(
        youtube_video_id="pin_hd",
        channel_id="pinterest_nature",
        channel_name="Pinterest",
        title="Full HD Nature Video",
        youtube_url="https://pinterest.com/pin/pin_hd",
        platform="pinterest",
        source_id="pin_hd",
        duration_seconds=15,
        width=1080,
        height=1920,
    )
    is_valid, reason = v_filter.evaluate_candidate(hd_cand)
    assert is_valid
    assert reason is None


def test_reject_rap_song_talha_anjum(test_setup):
    """Verify that rap songs by Talha Anjum, Young Stunners or drill artists are rejected."""
    _, config, v_filter = test_setup
    config.instagram_allow_rap = False

    rap_cand = VideoCandidate(
        youtube_video_id="rap1",
        channel_id="talha_anjum",
        channel_name="Talha Anjum",
        title="Told My Brother",
        youtube_url="https://instagram.com/reels/audio/rap1",
        platform="instagram",
        source_id="rap1",
        artist="Talha Anjum, Umair",
        audio_url="https://cdn.example.com/audio.mp3",
        duration_seconds=216,
    )
    is_valid, reason = v_filter.evaluate_candidate(rap_cand)
    assert is_valid is False
    assert "rap/hip-hop" in reason


def test_reject_rap_song_by_title_keyword(test_setup):
    """Verify that tracks with rap/diss keywords in title are rejected."""
    _, config, v_filter = test_setup
    config.instagram_allow_rap = False

    drill_cand = VideoCandidate(
        youtube_video_id="drill1",
        channel_id="artist1",
        channel_name="Artist",
        title="Karachi Drill Rap Diss Track",
        youtube_url="https://instagram.com/reels/audio/drill1",
        platform="instagram",
        source_id="drill1",
        artist="Underground Artist",
        audio_url="https://cdn.example.com/audio.mp3",
        duration_seconds=180,
    )
    is_valid, reason = v_filter.evaluate_candidate(drill_cand)
    assert is_valid is False
    assert "rap/hip-hop" in reason


def test_accept_soft_normal_song(test_setup):
    """Verify that soft normal songs are accepted."""
    _, config, v_filter = test_setup
    config.instagram_allow_rap = False

    soft_cand = VideoCandidate(
        youtube_video_id="soft1",
        channel_id="shanzy",
        channel_name="Shanzy Sial",
        title="Chalre Chalre Waal",
        youtube_url="https://instagram.com/reels/audio/soft1",
        platform="instagram",
        source_id="soft1",
        artist="Shanzy Sial",
        audio_url="https://cdn.example.com/audio.mp3",
        duration_seconds=139,
    )
    is_valid, reason = v_filter.evaluate_candidate(soft_cand)
    assert is_valid is True
    assert reason is None


def test_is_sad_song_detection():
    """Verify sad song detection accurately catches heartbreak/sad tracks."""
    from filters import is_sad_song
    assert is_sad_song("O Re Bewafa", "Asad Naeem") is True
    assert is_sad_song("Sajna da Dil Torya", "Zeeshan Ali") is True
    assert is_sad_song("Pyaar Kyun Banaya", "Nehaal Naseem") is True
    assert is_sad_song("Hamare Baad Mahfil Me", "Mizaa Mizaa") is True
    assert is_sad_song("Dard Bhari Ghazal", "Singer") is True
    assert is_sad_song("Slowed Reverb Sad Song", "Artist") is True
    assert is_sad_song("Baby Doll", "Kanika Kapoor") is False

