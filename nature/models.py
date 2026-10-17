"""Data models and type definitions for the Nature Cinematic Reel Maker."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class CompositionMode(str, Enum):
    CROP = "crop"
    FIT_WITH_BACKGROUND = "fit-with-background"
    BLURRED_BACKGROUND = "blurred-background"


class ReelStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class JobStage(str, Enum):
    IDLE = "IDLE"
    DISCOVERING = "DISCOVERING"
    FILTERING = "FILTERING"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    GENERATING_THOUGHTS = "GENERATING_THOUGHTS"
    RENDERING = "RENDERING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


@dataclass
class NatureCategory:
    """Predefined nature category with curated keyword variations."""

    id: str
    name: str
    description: str
    keywords: List[str]


@dataclass
class NatureProfile:
    """Configurable search profile for Nature Cinematic Reels."""

    name: str = "Nature Cinematic Reels"
    categories: List[str] = field(
        default_factory=lambda: [
            "mountains",
            "lakes_rivers",
            "sunsets_sunrises",
            "forests_waterfalls",
            "flowers_meadows",
        ]
    )
    custom_keywords: Dict[str, List[str]] = field(default_factory=dict)
    excluded_terms: List[str] = field(
        default_factory=lambda: [
            "person",
            "people",
            "face",
            "man",
            "woman",
            "vlog",
            "interview",
            "meme",
            "text",
            "quote",
            "dance",
            "car",
            "city",
            "building",
            "traffic",
            "commercial",
            "watermark",
        ]
    )
    search_limit: int = 15
    daily_processing_limit: int = 10
    min_quality_score: float = 65.0
    is_active: bool = True
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NatureQualityScore:
    """Detailed multi-factor quality inspection results."""

    overall_score: float = 0.0
    technical_score: float = 0.0
    visual_clarity_score: float = 0.0
    vertical_suitability_score: float = 0.0
    scenic_relevance_score: float = 0.0
    is_scenic: bool = False
    has_subject: bool = False
    is_eligible: bool = False  # Mandatory rights & reuse gate
    rejection_reasons: List[str] = field(default_factory=list)

    @property
    def passed_gate(self) -> bool:
        return self.is_eligible and len(self.rejection_reasons) == 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NatureCandidate:
    """Discovered candidate video clip."""

    source_id: str
    platform: str = "pinterest"
    title: str = ""
    canonical_url: str = ""
    category: str = "mountains"
    search_keyword: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    fps: Optional[float] = None
    bitrate: Optional[int] = None
    thumbnail_url: Optional[str] = None
    creator_attribution: Optional[str] = None
    quality_score: Optional[NatureQualityScore] = None
    eligibility_status: str = "ELIGIBLE"
    rejection_reason: Optional[str] = None
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if self.quality_score:
            data["quality_score"] = self.quality_score.to_dict()
        return data


@dataclass
class NatureTemplateConfig:
    """Settings for the Nature Cinematic — Thought Reel template."""

    name: str = "Nature Cinematic — Thought Reel"
    template_version: str = "1.0.0"
    composition_mode: str = CompositionMode.CROP.value
    canvas_width: int = 1080
    canvas_height: int = 1920
    target_duration: float = 10.0
    fps: int = 30
    font_path: str = "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf"
    font_style: str = "serif"  # 'serif' or 'serif-italic'
    font_size: int = 44
    text_position_y: str = "(h-text_h)/2 + 80"
    letterbox_bars: bool = False
    color_grade_preset: str = "restrained_warm"
    fade_duration: float = 0.6
    enable_shadow: bool = True
    enable_scrim: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NatureThought:
    """AI-generated poetic thought and caption metadata."""

    thought_text: str
    caption: str
    hashtags: List[str]
    title_hook: Optional[str] = None
    source_attribution: Optional[str] = None
    alternative_caption: Optional[str] = None
    theme: str = "peace_and_solitude"
    ai_provider: str = "groq"
    model_name: str = "openai/gpt-oss-20b"
    is_fallback: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NatureReel:
    """Completed or draft Nature Reel asset."""

    id: Optional[int] = None
    source_id: str = ""
    candidate_url: str = ""
    category: str = "mountains"
    keyword: str = ""
    original_video_path: str = ""
    rendered_reel_path: str = ""
    thumbnail_path: Optional[str] = None
    thought_text: str = ""
    caption: str = ""
    hashtags: List[str] = field(default_factory=list)
    title_hook: Optional[str] = None
    creator_attribution: Optional[str] = None
    template_name: str = "Nature Cinematic — Thought Reel"
    template_version: str = "1.0.0"
    composition_mode: str = CompositionMode.CROP.value
    duration_seconds: float = 10.0
    width: int = 1080
    height: int = 1920
    fps: int = 30
    ai_model_name: str = "openai/gpt-oss-20b"
    status: str = ReelStatus.PENDING.value
    drive_file_id: Optional[str] = None
    drive_link: Optional[str] = None
    uploaded_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
