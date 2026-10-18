import os
import pytest
from datetime import datetime, timezone, timedelta
from nature.models import (
    NatureProfile,
    NatureCandidate,
    RecencyPreference,
    SearchMood,
    SeasonPreference,
    PreferredOrientation,
)
from nature.profile import ProfileManager, DEFAULT_NATURE_CATEGORIES
from nature.quality_filter import NatureQualityFilter
from pinterest_discovery import parse_pinterest_timestamp
from database import Database


def test_keyword_library_categories_and_rotation():
    """Verify all 8 canonical categories exist with rich keyword libraries and rotation works."""
    expected_categories = [
        "autumn_forest",
        "misty_mountains",
        "forests_moss_rain",
        "lakes_rivers_waterfalls",
        "golden_hour_sunsets",
        "meadows_flowers",
        "snow_winter",
        "rare_premium",
    ]
    for cat in expected_categories:
        assert cat in DEFAULT_NATURE_CATEGORIES
        keywords = DEFAULT_NATURE_CATEGORIES[cat].keywords
        assert len(keywords) >= 10, f"Category {cat} should have at least 10 keywords"

    profile = NatureProfile()
    mgr = ProfileManager(profile)

    # Test keyword rotation for autumn_forest
    cat1, kw1 = mgr.get_next_keyword("autumn_forest")
    cat2, kw2 = mgr.get_next_keyword("autumn_forest")
    cat3, kw3 = mgr.get_next_keyword("autumn_forest")
    assert cat1 == "autumn_forest"
    assert kw1 != kw2 or kw2 != kw3


def test_smart_search_query_generation():
    """Verify smart combinations of category, mood, season, and orientation."""
    profile = NatureProfile()
    mgr = ProfileManager(profile)

    cat, base_kw, query = mgr.generate_search_query(
        category_id="misty_mountains",
        mood=SearchMood.MOODY.value,
        season=SeasonPreference.AUTUMN.value,
        orientation=PreferredOrientation.VERTICAL_9_16.value,
    )
    assert cat == "misty_mountains"
    assert "vertical" in query or "video" in query
    assert len(query.split()) >= 3


def test_pinterest_timestamp_parsing():
    """Test RFC 2822, ISO 8601, and invalid timestamp parsing."""
    # RFC 2822 (common from Pinterest created_at)
    parsed = parse_pinterest_timestamp("Fri, 12 Jun 2026 11:29:29 +0000")
    assert parsed == "2026-06-12T11:29:29+00:00"

    # ISO 8601
    parsed_iso = parse_pinterest_timestamp("2026-05-01T15:30:00Z")
    assert parsed_iso == "2026-05-01T15:30:00+00:00"

    # Missing / None / Empty
    assert parse_pinterest_timestamp(None) is None
    assert parse_pinterest_timestamp("") is None
    assert parse_pinterest_timestamp("invalid-date-string") is None


def test_recency_scoring_and_filtering():
    """Test recency scoring and unknown date handling."""
    profile = NatureProfile(recency_preference=RecencyPreference.LAST_6_MONTHS.value, strict_recency=False)
    qf = NatureQualityFilter(profile)

    now = datetime.now(timezone.utc)
    recent_date = (now - timedelta(days=30)).isoformat()
    old_date = (now - timedelta(days=400)).isoformat()

    # Recent candidate
    score_recent, status_recent, rej_recent = qf.calculate_recency_score(recent_date, "last_6_months", False)
    assert score_recent >= 90.0
    assert status_recent in ("recent", "very_recent")
    assert rej_recent is None

    # Old candidate with strict_recency=False
    score_old, status_old, rej_old = qf.calculate_recency_score(old_date, "last_6_months", False)
    assert score_old < 60.0
    assert status_old == "older"
    assert rej_old is None

    # Missing candidate date
    score_unk, status_unk, rej_unk = qf.calculate_recency_score(None, "last_6_months", False)
    assert score_unk == 70.0
    assert status_unk == "unknown"
    assert rej_unk is None

    # Strict recency mode rejects older content
    strict_profile = NatureProfile(recency_preference=RecencyPreference.LAST_6_MONTHS.value, strict_recency=True)
    strict_qf = NatureQualityFilter(strict_profile)
    cand_old = NatureCandidate(
        source_id="old123",
        title="Old Fall Foliage",
        published_at=old_date,
        raw_metadata={"is_video": True, "videos": {"video_list": {"v": {}}}},
    )
    pre_score, eligible, reasons = strict_qf.evaluate_pre_download(
        cand_old, recency_preference="last_6_months", strict_recency=True
    )
    assert not eligible
    assert any("exceeds 6 months" in r for r in reasons)


def test_pre_download_quality_ranking_and_negative_filters():
    """Verify non-videos and spam are rejected before downloading."""
    profile = NatureProfile()
    qf = NatureQualityFilter(profile)

    # 1. Non-video Pin rejected
    img_cand = NatureCandidate(
        source_id="img1",
        title="Beautiful Scenic Mountain Wallpaper",
        raw_metadata={"is_video": False},
    )
    score, eligible, reasons = qf.evaluate_pre_download(img_cand)
    assert not eligible
    assert "Candidate is not a video Pin" in reasons

    # 2. Anime / Gaming / Makeup negative terms rejected
    spam_cand = NatureCandidate(
        source_id="spam1",
        title="Anime aesthetic nature background gameplay 4K",
        raw_metadata={"is_video": True, "videos": {"video_list": {"v": {}}}},
    )
    score, eligible, reasons = qf.evaluate_pre_download(spam_cand)
    assert not eligible
    assert any("Contains excluded term" in r for r in reasons)

    # 3. High quality vertical nature video passes with high score
    good_cand = NatureCandidate(
        source_id="good1",
        title="Dreamy misty autumn forest walking trail cinematic",
        width=1080,
        height=1920,
        published_at=datetime.now(timezone.utc).isoformat(),
        raw_metadata={"is_video": True, "videos": {"video_list": {"v": {}}}},
    )
    score, eligible, reasons = qf.evaluate_pre_download(good_cand)
    assert eligible
    assert score >= 80.0
    assert good_cand.recency_status in ("recent", "very_recent")


def test_keyword_history_db(tmp_path):
    """Verify keyword history recording and retrieval in SQLite."""
    db_file = tmp_path / "test_downloads.db"
    db = Database(str(db_file))

    db.record_nature_keyword_search(
        category="autumn_forest",
        keyword="aesthetic autumn forest cinematic video",
        query="aesthetic autumn forest cinematic video vertical",
        mood="peaceful",
        season="autumn",
        candidates_found=15,
        videos_found=12,
        eligible_found=10,
    )

    history = db.get_nature_keyword_history(limit=5)
    assert len(history) == 1
    assert history[0]["keyword"] == "aesthetic autumn forest cinematic video"
    assert history[0]["query"] == "aesthetic autumn forest cinematic video vertical"
    assert history[0]["candidates_found"] == 15
    assert history[0]["eligible_found"] == 10
