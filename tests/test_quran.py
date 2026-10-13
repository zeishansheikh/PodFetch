"""Unit and integration tests for the Quran Ayah Reel Builder (Islamic Feature)."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from quran.key_rotator import GroqKeyRotator
from quran.manifest import ReelManifest
from quran.renderer import sanitize_no_em_dash, wrap_text_words
from quran.state import QuranState, ReelHistoryEntry, StateManager
from quran.tanzil import TanzilDatabase, normalize_arabic


class TestStateManager:
    """Test StateManager guarantees: strict next_index, ayah deduplication, background deduplication."""

    def test_default_state_initialization(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file=state_file)
        assert mgr.state.next_index == 1
        assert mgr.state.used_ayahs == []
        assert mgr.state.used_background_drive_ids == []
        assert mgr.state.used_background_pin_ids == []

    def test_advance_index_strictly_sequential(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file=state_file)
        assert mgr.state.next_index == 1
        idx2 = mgr.advance_index()
        assert idx2 == 2
        assert mgr.state.next_index == 2

        # Reload from disk
        mgr2 = StateManager(state_file=state_file)
        assert mgr2.state.next_index == 2

    def test_used_ayah_tracking(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file=state_file)
        assert not mgr.is_ayah_used(1, 1)

        mgr.mark_ayah_used(1, 1)
        assert mgr.is_ayah_used(1, 1)
        assert not mgr.is_ayah_used(1, 2)

        # Persistence check
        mgr_reloaded = StateManager(state_file=state_file)
        assert mgr_reloaded.is_ayah_used(1, 1)

    def test_used_background_tracking(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file=state_file)

        assert not mgr.is_background_used(pin_id="pin_123")
        assert not mgr.is_background_used(drive_id="drive_abc")

        mgr.mark_background_used(pin_id="pin_123", drive_id="drive_abc")

        assert mgr.is_background_used(pin_id="pin_123")
        assert mgr.is_background_used(drive_id="drive_abc")
        assert not mgr.is_background_used(pin_id="pin_999")

    def test_add_history_entry(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        mgr = StateManager(state_file=state_file)

        entry = ReelHistoryEntry(
            date="2026-10-13",
            surah_number=1,
            ayah_number=5,
            surah_name_english="Al-Fatihah",
            surah_name_arabic="الفاتحة",
            reel_path="ready/reel_2026-10-13.mp4",
            duration_seconds=9.58,
            drive_file_id="drive_file_123",
            drive_link="https://drive.google.com/file/d/drive_file_123/view",
            playlist_video_id="vid_test",
            playlist_index=1,
        )
        mgr.add_history(entry)

        assert len(mgr.state.history) == 1
        assert mgr.is_ayah_used(1, 5)
        assert mgr.is_background_used(drive_id="drive_file_123")


class TestTanzilDatabase:
    """Test Tanzil Uthmani database loading, Arabic normalization, and fuzzy matching."""

    def test_arabic_normalization(self):
        raw = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"
        normalized = normalize_arabic(raw)
        # Tashkeel, superscript alef, and wasla must be stripped
        assert "ِ" not in normalized
        assert "َ" not in normalized
        assert "ّ" not in normalized
        assert "بسم" in normalized
        assert "الله" in normalized

    def test_tanzil_loading_and_matching(self):
        db = TanzilDatabase()
        # Tanzil must contain full 114 surahs and 6236 verses
        assert len(db.verses) == 6236
        assert len(db.surahs) == 114

        # Test exact/fuzzy match for Al-Fatihah 1:1
        match = db.fuzzy_match("بسم الله الرحمن الرحيم", surah_hint=1)
        assert match is not None
        assert match.surah_number == 1
        assert match.ayah_number == 1
        assert match.confidence >= 0.90
        # Critical contract rule: on-screen Arabic comes from Tanzil with authentic Uthmani diacritics
        assert match.arabic_uthmani == "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"
        assert "رحم والا" in match.urdu_translation

    def test_tanzil_fuzzy_match_low_confidence_rejection(self):
        db = TanzilDatabase()
        # Bogus query must fail match threshold
        match = db.fuzzy_match("هذا نص عشوائي لا يوجد في القرآن إطلاقا", min_confidence=0.85)
        assert match is None


class TestGroqKeyRotator:
    """Test Groq API key rotation mechanism."""

    def test_key_rotation_cycles(self):
        keys = ["key_A", "key_B", "key_C"]
        rotator = GroqKeyRotator(keys=keys)
        assert rotator.get_current_key() == "key_A"

        rotator.rotate_key(reason="test limit")
        assert rotator.get_current_key() == "key_B"

        rotator.rotate_key(reason="test limit")
        assert rotator.get_current_key() == "key_C"

        rotator.rotate_key(reason="test limit")
        assert rotator.get_current_key() == "key_A"  # Wraps around


class TestReelManifest:
    """Test contract manifest schema and validation rules."""

    def test_manifest_validation_success(self):
        manifest = ReelManifest(
            reel_file="ready/reel_2026-10-13.mp4",
            date="2026-10-13",
            surah_number=1,
            ayah_number=1,
            ayah_end=None,
            surah_name_english="Al-Fatihah",
            surah_name_arabic="الفاتحة",
            arabic_text="بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ",
            urdu_translation="شروع الله کا نام لے کر جو بڑا مہربان نہایت رحم والا ہے",
            caption="In the name of Allah, the Most Compassionate, the Most Merciful.",
            hashtags=["#Quran", "#Islam", "#AyahOfTheDay"],
            duration_seconds=9.38,
            drive_file_id="drive_id_123",
            drive_link="https://drive.google.com/file/d/drive_id_123/view",
        )
        manifest.validate()  # Must not raise

    def test_manifest_rejects_more_than_three_hashtags(self):
        manifest = ReelManifest(
            reel_file="ready/reel_2026-10-13.mp4",
            date="2026-10-13",
            surah_number=1,
            ayah_number=1,
            ayah_end=None,
            surah_name_english="Al-Fatihah",
            surah_name_arabic="الفاتحة",
            arabic_text="بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ",
            urdu_translation="شروع الله کا نام لے کر",
            caption="Caption text",
            hashtags=["#Quran", "#Islam", "#AyahOfTheDay", "#ExtraTag"],
            duration_seconds=9.38,
        )
        with pytest.raises(ValueError, match="exactly 3 hashtags"):
            manifest.validate()

    def test_manifest_rejects_em_dash(self):
        manifest = ReelManifest(
            reel_file="ready/reel_2026-10-13.mp4",
            date="2026-10-13",
            surah_number=1,
            ayah_number=1,
            ayah_end=None,
            surah_name_english="Al-Fatihah",
            surah_name_arabic="الفاتحة",
            arabic_text="بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ",
            urdu_translation="شروع الله کا نام لے کر",
            caption="In the name of Allah — the Most Compassionate",  # Contains em-dash
            hashtags=["#Quran", "#Islam", "#AyahOfTheDay"],
            duration_seconds=9.38,
        )
        with pytest.raises(ValueError, match="Forbidden em-dash"):
            manifest.validate()


class TestTextSanitization:
    """Test em-dash and punctuation removal."""

    def test_sanitize_no_em_dash(self):
        dirty = "The Creator — Almighty – Lord (Praise be to Him)"
        clean = sanitize_no_em_dash(dirty)
        assert "—" not in clean
        assert "–" not in clean
        assert "(" not in clean
        assert ")" not in clean
        assert clean == "The Creator  -  Almighty  -  Lord Praise be to Him"

    def test_wrap_text_words(self):
        text = "word1 word2 word3 word4 word5 word6"
        wrapped = wrap_text_words(text, max_chars=15)
        lines = wrapped.split("\n")
        assert len(lines) >= 2
        for line in lines:
            assert len(line) <= 18
