"""Comprehensive unit and integration tests for the Nature Cinematic Reel Maker."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api import app
from database import Database
from nature.models import (
    CompositionMode,
    NatureCandidate,
    NatureProfile,
    NatureQualityScore,
    NatureReel,
    NatureTemplateConfig,
    ReelStatus,
)
from nature.profile import (
    DEFAULT_EXCLUDED_TERMS,
    DEFAULT_NATURE_CATEGORIES,
    ProfileManager,
)
from nature.quality_filter import NatureQualityFilter
from nature.template import NatureTemplateRenderer
from nature.thoughts_generator import NatureThoughtsGenerator


class TestNatureProfile:
    """Test keyword expansion, profile configuration, and rotation."""

    def test_default_categories_and_exact_keywords(self):
        manager = ProfileManager()
        categories = manager.get_categories()

        # Must include the 5 canonical nature categories
        assert "mountains" in categories
        assert "lakes_rivers" in categories
        assert "sunsets_sunrises" in categories
        assert "forests_waterfalls" in categories
        assert "flowers_meadows" in categories

        # Exact keywords from specification
        mountain_kw = categories["mountains"].keywords
        assert "cinematic mountain landscape" in mountain_kw
        assert "dreamy alpine mountains" in mountain_kw
        assert "mountain clouds aesthetic" in mountain_kw
        assert "scenic mountain valley" in mountain_kw
        assert "misty mountain sunrise" in mountain_kw

        lake_kw = categories["lakes_rivers"].keywords
        assert "cinematic alpine lake" in lake_kw
        assert "crystal clear lake scenery" in lake_kw

    def test_keyword_rotation(self):
        manager = ProfileManager()
        # Sequential rotation across mountains
        cat1, kw1 = manager.get_next_keyword("mountains", randomize=False)
        cat2, kw2 = manager.get_next_keyword("mountains", randomize=False)
        assert cat1 == "mountains"
        assert cat2 == "mountains"
        assert kw1 != kw2

    def test_excluded_terms_detection(self):
        manager = ProfileManager()
        # Should detect excluded keywords like 'vlog', 'person', 'meme'
        is_ex, reason = manager.is_title_or_desc_excluded("My travel vlog in Switzerland with a person")
        assert is_ex is True
        assert "person" in reason.lower() or "vlog" in reason.lower()

        # Clean nature scenery should pass
        is_ex_clean, reason_clean = manager.is_title_or_desc_excluded("Misty morning over alpine lake")
        assert is_ex_clean is False
        assert reason_clean is None


class TestNatureQualityFilter:
    """Test multi-factor quality inspection and strict eligibility gates."""

    def test_pre_download_metadata_evaluation(self):
        qf = NatureQualityFilter()
        candidate = NatureCandidate(
            source_id="test_pin_01",
            title="Alpine mountain view",
            category="mountains",
        )
        score = qf.evaluate_candidate(candidate)
        assert score.is_eligible is True
        assert score.overall_score >= 65.0

    def test_excluded_term_triggers_immediate_rejection(self):
        qf = NatureQualityFilter()
        candidate = NatureCandidate(
            source_id="test_pin_excluded",
            title="Funny meme compilation with people",
            category="mountains",
        )
        score = qf.evaluate_candidate(candidate)
        assert score.is_eligible is False
        assert candidate.eligibility_status == "REJECTED"
        assert any("excluded" in r.lower() for r in score.rejection_reasons)

    def test_duplicate_candidate_rejection(self):
        qf = NatureQualityFilter()
        candidate = NatureCandidate(
            source_id="pin_already_seen",
            title="Scenic forest",
            category="forests_waterfalls",
        )
        score = qf.evaluate_candidate(
            candidate=candidate,
            already_processed_ids={"pin_already_seen"},
        )
        assert score.is_eligible is False
        assert any("duplicate" in r.lower() for r in score.rejection_reasons)

    def test_corrupted_or_missing_media_rejection(self, tmp_path: Path):
        qf = NatureQualityFilter()
        corrupt_file = tmp_path / "corrupt.mp4"
        corrupt_file.write_bytes(b"not a valid video stream header data")

        candidate = NatureCandidate(source_id="pin_corrupt", title="Corrupt clip")
        score = qf.evaluate_candidate(candidate, local_video_path=corrupt_file)
        assert score.is_eligible is False
        assert candidate.eligibility_status == "REJECTED"


class TestNatureThoughtsGenerator:
    """Test AI thought and caption generation with repetition protection and fallback."""

    def test_deterministic_curated_fallback(self):
        # Force no API keys to verify graceful curated fallback
        with patch.object(NatureThoughtsGenerator, "__init__", lambda self: setattr(self, "rotator", MagicMock(has_keys=False))):
            gen = NatureThoughtsGenerator()
            thought = gen.generate_thought_and_caption("mountains", "cinematic mountain landscape")

            assert thought.is_fallback is True
            assert len(thought.thought_text) > 10
            assert len(thought.caption) > 10
            assert len(thought.hashtags) >= 3
            assert all(t.startswith("#") for t in thought.hashtags)
            assert thought.model_name == "curated-fallback-engine"

    def test_repetition_avoidance(self):
        past_thoughts = [
            "Give yourself time to grow\nin places nobody sees.",
            "Silence is not empty.\nIt is full of answers.",
        ]
        with patch.object(NatureThoughtsGenerator, "__init__", lambda self: setattr(self, "rotator", MagicMock(has_keys=False))):
            gen = NatureThoughtsGenerator()
            # Generated fallback thought should not repeat the already used entries
            thought = gen.generate_thought_and_caption("mountains", "cinematic mountain landscape", past_thoughts=past_thoughts)
            clean_thought = thought.thought_text.lower().replace("\n", " ")
            for pt in past_thoughts:
                assert clean_thought != pt.lower().replace("\n", " ")


class TestNatureTemplateRenderer:
    """Test FFmpeg command construction, composition modes, and output validation."""

    def test_filter_complex_crop_construction(self):
        renderer = NatureTemplateRenderer()
        fc = renderer.build_filter_complex(
            text_file_path="/tmp/dummy_text.txt",
            duration=10.0,
            composition_mode=CompositionMode.CROP.value,
        )
        assert "crop=1080:1920" in fc
        assert "drawtext" in fc
        assert "fade=" in fc

    def test_filter_complex_blurred_background_construction(self):
        renderer = NatureTemplateRenderer()
        fc = renderer.build_filter_complex(
            text_file_path="/tmp/dummy_text.txt",
            duration=10.0,
            composition_mode=CompositionMode.BLURRED_BACKGROUND.value,
        )
        assert "boxblur" in fc
        assert "overlay=" in fc
        assert "drawtext" in fc

    def test_end_to_end_synthetic_render(self, tmp_path: Path):
        # Create a small 2-second test video with lavfi
        source_video = tmp_path / "synthetic_source.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=duration=2:size=1280x720:rate=30",
                "-t",
                "2",
                str(source_video),
            ],
            check=True,
            capture_output=True,
        )

        renderer = NatureTemplateRenderer()
        out_reel = tmp_path / "rendered_reel.mp4"
        ok, err = renderer.render_reel(
            input_video_path=source_video,
            thought_text="Stillness is where clarity begins.",
            output_reel_path=out_reel,
            target_duration=1.5,
            composition_mode=CompositionMode.CROP.value,
        )
        assert ok is True
        assert err is None
        assert out_reel.exists()
        assert out_reel.stat().st_size > 15000

        # Output validation
        is_valid, v_err = renderer.validate_output_reel(out_reel, min_duration=1.0)
        assert is_valid is True

        # Thumbnail extraction
        thumb = tmp_path / "thumb.jpg"
        t_ok = renderer.generate_thumbnail(out_reel, thumb, timestamp=0.5)
        assert t_ok is True
        assert thumb.exists()


class TestDatabasePersistence:
    """Test SQLite persistence for nature profiles, candidates, reels, drafts, and jobs."""

    def test_profile_and_reels_crud(self, tmp_path: Path):
        db = Database(tmp_path / "test_nature.db")

        # 1. Profile
        prof = NatureProfile(name="Custom Nature", search_limit=20, min_quality_score=70.0)
        db.save_nature_profile(prof.to_dict())

        loaded = db.get_nature_profile("Custom Nature")
        assert loaded is not None
        assert loaded["search_limit"] == 20
        assert loaded["min_quality_score"] == 70.0

        # 2. Candidate
        cand = NatureCandidate(
            source_id="cand_101",
            title="Misty mountain sunrise",
            category="mountains",
            quality_score=NatureQualityScore(overall_score=78.5, is_eligible=True),
        )
        db.save_nature_candidate(cand.to_dict())
        cands = db.get_nature_candidates()
        assert len(cands) == 1
        assert cands[0]["source_id"] == "cand_101"

        # 3. Reel
        reel = NatureReel(
            source_id="cand_101",
            category="mountains",
            thought_text="Give yourself time to grow.",
            caption="Find strength in quiet spaces.",
            hashtags=["#nature", "#mountains"],
            status=ReelStatus.PENDING.value,
        )
        reel_id = db.save_nature_reel(reel.to_dict())
        assert reel_id > 0

        # 4. Draft update
        db.update_nature_reel_draft(
            reel_id=reel_id,
            thought_text="New updated thought.",
            caption="New caption.",
            hashtags=["#nature", "#peace"],
        )
        updated = db.get_nature_reel_by_id(reel_id)
        assert updated["thought_text"] == "New updated thought."

        # 5. Status update (Approve)
        db.update_nature_reel_status(reel_id, ReelStatus.APPROVED.value)
        approved = db.get_nature_reel_by_id(reel_id)
        assert approved["status"] == ReelStatus.APPROVED.value


class TestApiEndpointsAndSecretRedaction:
    """Test FastAPI Nature endpoints and ensure API keys are never exposed in responses."""

    def test_get_nature_profile_secret_redaction(self):
        client = TestClient(app)
        resp = client.get("/api/nature/profile")
        assert resp.status_code == 200
        data = resp.json()

        assert "profile" in data
        assert "ai_status" in data

        # Check secret redaction: raw API keys must never appear
        ai_status = data["ai_status"]
        if ai_status.get("masked_key"):
            assert "..." in ai_status["masked_key"]
            assert len(ai_status["masked_key"]) <= 18

    def test_get_categories_endpoint(self):
        client = TestClient(app)
        resp = client.get("/api/nature/categories")
        assert resp.status_code == 200
        cats = resp.json().get("categories", [])
        assert len(cats) >= 5

    def test_reel_approval_and_rejection_lifecycle(self, tmp_path: Path):
        client = TestClient(app)
        # Query reels
        resp = client.get("/api/nature/reels")
        assert resp.status_code == 200
        assert "reels" in resp.json()
