"""Tanzil Quran text loader and Arabic fuzzy-matcher module.
Ensures authentic on-screen Uthmani script and Urdu translation directly from
official Tanzil text files (Contract Section 6, Step 5).
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from logger import get_logger

logger = get_logger("quran_tanzil")

TANZIL_UTHMANI_URL = "https://tanzil.net/pub/download/index.php?quranType=uthmani&outType=txt-2&agree=true"
TANZIL_URDU_URL = "https://tanzil.net/trans/ur.jalandhry"

# Surah metadata table: 1 to 114 (English Name, Arabic Name)
SURAH_METADATA: Dict[int, Tuple[str, str]] = {
    1: ("Al-Fatihah", "الفاتحة"),
    2: ("Al-Baqarah", "البقرة"),
    3: ("Ali 'Imran", "آل عمران"),
    4: ("An-Nisa", "النساء"),
    5: ("Al-Ma'idah", "المائدة"),
    6: ("Al-An'am", "الأنعام"),
    7: ("Al-A'raf", "الأعراف"),
    8: ("Al-Anfal", "الأنفال"),
    9: ("At-Tawbah", "التوبة"),
    10: ("Yunus", "يونس"),
    11: ("Hud", "هود"),
    12: ("Yusuf", "يوسف"),
    13: ("Ar-Ra'd", "الرعد"),
    14: ("Ibrahim", "إبراهيم"),
    15: ("Al-Hijr", "الحجر"),
    16: ("An-Nahl", "النحل"),
    17: ("Al-Isra", "الإسراء"),
    18: ("Al-Kahf", "الكهف"),
    19: ("Maryam", "مريم"),
    20: ("Taha", "طه"),
    21: ("Al-Anbiya", "الأنبياء"),
    22: ("Al-Hajj", "الحج"),
    23: ("Al-Mu'minun", "المؤمنون"),
    24: ("An-Nur", "النور"),
    25: ("Al-Furqan", "الفرقان"),
    26: ("Ash-Shu'ara", "الشعراء"),
    27: ("An-Naml", "النمل"),
    28: ("Al-Qasas", "القصص"),
    29: ("Al-'Ankabut", "العنكبوت"),
    30: ("Ar-Rum", "الروم"),
    31: ("Luqman", "لقمان"),
    32: ("As-Sajdah", "السجدة"),
    33: ("Al-Ahzab", "الأحزاب"),
    34: ("Saba", "سبأ"),
    35: ("Fatir", "فاطر"),
    36: ("Ya-Sin", "يس"),
    37: ("As-Saffat", "الصافات"),
    38: ("Sad", "ص"),
    39: ("Az-Zumar", "الزمر"),
    40: ("Ghafir", "غافر"),
    41: ("Fussilat", "فصلت"),
    42: ("Ash-Shura", "الشورى"),
    43: ("Az-Zukhruf", "الزخرف"),
    44: ("Ad-Dukhan", "الدخان"),
    45: ("Al-Jathiyah", "الجاثية"),
    46: ("Al-Ahqaf", "الأحقاف"),
    47: ("Muhammad", "محمد"),
    48: ("Al-Fath", "الفتح"),
    49: ("Al-Hujurat", "الحجرات"),
    50: ("Qaf", "ق"),
    51: ("Adh-Dhariyat", "الذاريات"),
    52: ("At-Tur", "الطور"),
    53: ("An-Najm", "النجم"),
    54: ("Al-Qamar", "القمر"),
    55: ("Ar-Rahman", "الرحمن"),
    56: ("Al-Waqi'ah", "الواقعة"),
    57: ("Al-Hadid", "الحديد"),
    58: ("Al-Mujadila", "المجادلة"),
    59: ("Al-Hashr", "الحشر"),
    60: ("Al-Mumtahanah", "الممتحنة"),
    61: ("As-Saff", "الصف"),
    62: ("Al-Jumu'ah", "الجمعة"),
    63: ("Al-Munafiqun", "المنافقون"),
    64: ("At-Taghabun", "التغابن"),
    65: ("At-Talaq", "الطلاق"),
    66: ("At-Tahrim", "التحريم"),
    67: ("Al-Mulk", "الملك"),
    68: ("Al-Qalam", "القلم"),
    69: ("Al-Haqqah", "الحاقة"),
    70: ("Al-Ma'arij", "المعارج"),
    71: ("Nuh", "نوح"),
    72: ("Al-Jinn", "الجن"),
    73: ("Al-Muzzammil", "المزمل"),
    74: ("Al-Muddaththir", "المدثر"),
    75: ("Al-Qiyamah", "القيامة"),
    76: ("Al-Insan", "الإنسان"),
    77: ("Al-Mursalat", "المرسلات"),
    78: ("An-Naba", "النبأ"),
    79: ("An-Nazi'at", "النازعات"),
    80: ("'Abasa", "عبس"),
    81: ("At-Takwir", "التكوير"),
    82: ("Al-Infitar", "الانفطار"),
    83: ("Al-Mutaffifin", "المطففين"),
    84: ("Al-Inshiqaq", "الانشقاق"),
    85: ("Al-Buruj", "البروج"),
    86: ("At-Tariq", "الطارق"),
    87: ("Al-A'la", "الأعلى"),
    88: ("Al-Ghashiyah", "الغاشية"),
    89: ("Al-Fajr", "الفجر"),
    90: ("Al-Balad", "البلد"),
    91: ("Ash-Shams", "الشمس"),
    92: ("Al-Layl", "الليل"),
    93: ("Ad-Duha", "الضحى"),
    94: ("Ash-Sharh", "الشرح"),
    95: ("At-Tin", "التين"),
    96: ("Al-'Alaq", "العلق"),
    97: ("Al-Qadr", "القدر"),
    98: ("Al-Bayyinah", "البينة"),
    99: ("Az-Zalzalah", "الزلزلة"),
    100: ("Al-'Adiyat", "العاديات"),
    101: ("Al-Qari'ah", "القارعة"),
    102: ("At-Takathur", "التكاثر"),
    103: ("Al-'Asr", "العصر"),
    104: ("Al-Humazah", "الهمزة"),
    105: ("Al-Fil", "الفيل"),
    106: ("Quraysh", "قريش"),
    107: ("Al-Ma'un", "الماعون"),
    108: ("Al-Kawthar", "الكوثر"),
    109: ("Al-Kafirun", "الكافرون"),
    110: ("An-Nasr", "النصر"),
    111: ("Al-Masad", "المسد"),
    112: ("Al-Ikhlas", "الإخلاص"),
    113: ("Al-Falaq", "الفلق"),
    114: ("An-Nas", "الناس"),
}


def normalize_arabic(text: str) -> str:
    """Strip diacritics, normalize letter shapes, and clean Quranic pause marks for comparison."""
    if not text:
        return ""
    # Strip tashkeel, harakat, superscript alefs, pause marks, tatweel
    s = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]", "", text)
    # Normalize alifs: إ أ آ ٱ -> ا
    s = re.sub(r"[إأآٱ]", "ا", s)
    # Normalize yaa and alif maqsura: ى ي -> ي
    s = re.sub(r"[ىي]", "ي", s)
    # Normalize taa marbuta: ة -> ه
    s = re.sub(r"ة", "ه", s)
    # Normalize hamza: ؤ ئ -> ء
    s = re.sub(r"[ؤئ]", "ء", s)
    # Remove all non-arabic characters except spaces
    s = re.sub(r"[^\u0621-\u063A\u0641-\u064A\s]", " ", s)
    return " ".join(s.split())


@dataclass
class AyahRecord:
    """Parsed verse record from Tanzil."""

    surah: int
    ayah: int
    uthmani_text: str
    urdu_translation: str
    normalized_text: str


@dataclass
class TanzilMatch:
    """Exact resolution result from fuzzy-matching against Tanzil text."""

    surah_number: int
    ayah_number: int
    ayah_end: Optional[int] = None
    arabic_uthmani: str = ""
    urdu_translation: str = ""
    surah_name_english: str = ""
    surah_name_arabic: str = ""
    confidence: float = 0.0


class TanzilDatabase:
    """Loads and indexes the official Tanzil Quran text and Urdu translation."""

    _instance: Optional[TanzilDatabase] = None

    def __init__(self, assets_dir: Optional[Path] = None) -> None:
        self.assets_dir = assets_dir or Path("quran/assets")
        self.uthmani_path = self._resolve_file("quran-uthmani.txt")
        self.urdu_path = self._resolve_file("quran-urdu.txt")
        self.verses: List[AyahRecord] = []
        self.verses_by_id: Dict[Tuple[int, int], AyahRecord] = {}
        self._ensure_files()
        self._load()

    def _resolve_file(self, filename: str) -> Path:
        """Check quran/assets, root assets, and local directory."""
        candidates = [
            self.assets_dir / filename,
            Path("assets") / filename,
            Path(filename),
        ]
        for c in candidates:
            if c.exists():
                return c
        return self.assets_dir / filename

    def _ensure_files(self) -> None:
        """Download Tanzil text files on first run if missing."""
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        if not self.uthmani_path.exists():
            logger.info(f"Downloading Tanzil Uthmani text from {TANZIL_UTHMANI_URL}...")
            try:
                urllib.request.urlretrieve(TANZIL_UTHMANI_URL, self.uthmani_path)
                logger.info(f"Saved Tanzil Uthmani text to {self.uthmani_path}")
            except Exception as e:
                logger.error(f"Failed to download Tanzil Uthmani text: {e}")

        if not self.urdu_path.exists():
            logger.info(f"Downloading Tanzil Urdu translation from {TANZIL_URDU_URL}...")
            try:
                urllib.request.urlretrieve(TANZIL_URDU_URL, self.urdu_path)
                logger.info(f"Saved Tanzil Urdu translation to {self.urdu_path}")
            except Exception as e:
                logger.error(f"Failed to download Tanzil Urdu translation: {e}")

    def _load(self) -> None:
        """Load and parse verses into memory with normalized lookup keys."""
        urdu_map: Dict[Tuple[int, int], str] = {}
        if self.urdu_path.exists():
            try:
                for line in self.urdu_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "|" not in line:
                        continue
                    parts = line.split("|", 2)
                    if len(parts) >= 3:
                        try:
                            s, a, text = int(parts[0]), int(parts[1]), parts[2].strip()
                            urdu_map[(s, a)] = text
                        except ValueError:
                            continue
            except Exception as e:
                logger.warning(f"Error reading Urdu translation file: {e}")

        if self.uthmani_path.exists():
            try:
                for line in self.uthmani_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "|" not in line:
                        continue
                    parts = line.split("|", 2)
                    if len(parts) >= 3:
                        try:
                            s, a, text = int(parts[0]), int(parts[1]), parts[2].strip()
                            urdu_text = urdu_map.get((s, a), "")
                            norm = normalize_arabic(text)
                            rec = AyahRecord(
                                surah=s,
                                ayah=a,
                                uthmani_text=text,
                                urdu_translation=urdu_text,
                                normalized_text=norm,
                            )
                            self.verses.append(rec)
                            self.verses_by_id[(s, a)] = rec
                        except ValueError:
                            continue
                logger.info(f"Loaded {len(self.verses)} Quran verses from Tanzil text.")
            except Exception as e:
                logger.error(f"Error loading Tanzil Uthmani text: {e}")

    @property
    def surahs(self) -> Dict[int, Tuple[str, str]]:
        """Dictionary of 114 Surah numbers to (English, Arabic) names."""
        return SURAH_METADATA

    def get_verse(self, surah: int, ayah: int) -> Optional[AyahRecord]:
        """Fetch verse record by exact surah and ayah number."""
        return self.verses_by_id.get((surah, ayah))

    def fuzzy_match(
        self,
        query_arabic: str,
        surah_hint: Optional[int] = None,
        min_confidence: float = 0.70,
    ) -> Optional[TanzilMatch]:
        """Fuzzy match Arabic text against official Tanzil verses.

        Returns:
            TanzilMatch with exact Tanzil text if confidence >= min_confidence, else None.
        """
        norm_query = normalize_arabic(query_arabic)
        if not norm_query:
            return None

        candidates_pool = self.verses
        if surah_hint and surah_hint in SURAH_METADATA:
            # First attempt searching within the hinted surah
            hinted = [v for v in self.verses if v.surah == surah_hint]
            if hinted:
                candidates_pool = hinted

        best_score = 0.0
        best_record: Optional[AyahRecord] = None
        best_range: Optional[Tuple[int, int]] = None

        # 1. Single verse matching
        for v in candidates_pool:
            ratio = difflib.SequenceMatcher(None, norm_query, v.normalized_text).ratio()
            
            # If the entire query is contained within this verse
            if norm_query in v.normalized_text:
                coverage = len(norm_query) / max(len(v.normalized_text), 1)
                # Boost if query covers most of the verse or if it is an exact sentence
                sub_score = 0.90 + (0.10 * coverage)
                ratio = max(ratio, sub_score)
            elif v.normalized_text in norm_query:
                # Verse is a small piece of query (e.g. query has extra recitation intro/words)
                coverage = len(v.normalized_text) / max(len(norm_query), 1)
                sub_score = 0.70 + (0.25 * coverage)
                ratio = max(ratio, sub_score)

            # Apply surah hint boost if hinted
            if surah_hint and v.surah == surah_hint:
                ratio = min(1.0, ratio + 0.08)

            if ratio > best_score:
                best_score = ratio
                best_record = v
                best_range = None

        # 2. Check 2 contiguous verses if score is modest
        if best_score < 0.90:
            for i in range(len(candidates_pool) - 1):
                v1 = candidates_pool[i]
                v2 = candidates_pool[i + 1]
                if v1.surah == v2.surah and v2.ayah == v1.ayah + 1:
                    comb_norm = f"{v1.normalized_text} {v2.normalized_text}"
                    ratio = difflib.SequenceMatcher(None, norm_query, comb_norm).ratio()
                    if norm_query in comb_norm or comb_norm in norm_query:
                        len_ratio = min(len(norm_query), len(comb_norm)) / max(len(norm_query), len(comb_norm), 1)
                        sub_score = 0.85 + (0.15 * len_ratio)
                        ratio = max(ratio, sub_score)

                    if ratio > best_score:
                        best_score = ratio
                        best_record = v1
                        best_range = (v1.ayah, v2.ayah)

        # Fallback to entire Quran pool if hinted search failed to achieve min_confidence
        if best_score < min_confidence and candidates_pool != self.verses:
            return self.fuzzy_match(query_arabic, surah_hint=None, min_confidence=min_confidence)

        if best_score < min_confidence or best_record is None:
            logger.warning(
                f"Tanzil fuzzy match confidence {best_score:.3f} below required {min_confidence:.2f} threshold."
            )
            return None

        s_num = best_record.surah
        a_start = best_record.ayah
        surah_en, surah_ar = SURAH_METADATA.get(s_num, (f"Surah {s_num}", f"سورة {s_num}"))

        if best_range:
            v2 = self.verses_by_id.get((s_num, best_range[1]))
            arabic_text = f"{best_record.uthmani_text} {v2.uthmani_text}" if v2 else best_record.uthmani_text
            urdu_text = f"{best_record.urdu_translation} {v2.urdu_translation}".strip() if v2 else best_record.urdu_translation
            return TanzilMatch(
                surah_number=s_num,
                ayah_number=a_start,
                ayah_end=best_range[1],
                arabic_uthmani=arabic_text,
                urdu_translation=urdu_text,
                surah_name_english=surah_en,
                surah_name_arabic=surah_ar,
                confidence=round(best_score, 4),
            )

        return TanzilMatch(
            surah_number=s_num,
            ayah_number=a_start,
            ayah_end=None,
            arabic_uthmani=best_record.uthmani_text,
            urdu_translation=best_record.urdu_translation,
            surah_name_english=surah_en,
            surah_name_arabic=surah_ar,
            confidence=round(best_score, 4),
        )


def get_tanzil_db(assets_dir: Optional[Path] = None) -> TanzilDatabase:
    """Singleton getter for Tanzil database."""
    if TanzilDatabase._instance is None:
        TanzilDatabase._instance = TanzilDatabase(assets_dir)
    return TanzilDatabase._instance
