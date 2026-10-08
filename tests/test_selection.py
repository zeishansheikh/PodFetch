"""
Unit tests for fair channel distribution and selection algorithms.
"""

from datetime import datetime, timezone
from filters import VideoCandidate
from discovery import select_videos_for_run


def make_cand(vid: str, ch_id: str, title: str) -> VideoCandidate:
    return VideoCandidate(
        youtube_video_id=vid,
        channel_id=ch_id,
        channel_name=f"Channel {ch_id}",
        title=title,
        youtube_url=f"https://youtube.com/watch?v={vid}",
        published_at=datetime.now(timezone.utc),
        duration_seconds=3600,
    )


def test_fair_distribution_prioritizes_underrepresented_channels():
    # Channels A, B, C, D
    # A has 10 past uploads, B has 8, C has 1, D has 0
    hist_counts = {"ch_A": 10, "ch_B": 8, "ch_C": 1, "ch_D": 0}

    candidates_by_channel = {
        "ch_A": [make_cand("vA1", "ch_A", "Ep A1")],
        "ch_B": [make_cand("vB1", "ch_B", "Ep B1")],
        "ch_C": [make_cand("vC1", "ch_C", "Ep C1")],
        "ch_D": [make_cand("vD1", "ch_D", "Ep D1")],
    }

    # Request exactly 2 videos
    selected = select_videos_for_run(
        eligible_by_channel=candidates_by_channel,
        min_count=2,
        max_count=2,
        historical_counts=hist_counts,
        exact_limit=2,
    )

    assert len(selected) == 2
    selected_ch_ids = {c.channel_id for c in selected}
    # D (0) and C (1) should be chosen over A (10) and B (8)
    assert "ch_D" in selected_ch_ids
    assert "ch_C" in selected_ch_ids


def test_selection_limits_honored():
    candidates_by_channel = {
        "ch_A": [make_cand("vA1", "ch_A", "Ep A1"), make_cand("vA2", "ch_A", "Ep A2")],
        "ch_B": [make_cand("vB1", "ch_B", "Ep B1")],
    }
    # Exact limit override
    selected = select_videos_for_run(
        eligible_by_channel=candidates_by_channel,
        min_count=1,
        max_count=3,
        historical_counts={},
        exact_limit=1,
    )
    assert len(selected) == 1


def test_selection_never_exceeds_available():
    candidates_by_channel = {
        "ch_A": [make_cand("vA1", "ch_A", "Ep A1")],
    }
    selected = select_videos_for_run(
        eligible_by_channel=candidates_by_channel,
        min_count=2,
        max_count=5,
        historical_counts={},
    )
    assert len(selected) == 1
