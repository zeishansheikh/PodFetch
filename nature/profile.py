"""Nature search profile manager with rotation, customization, and category keywords."""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple
from nature.models import NatureCategory, NatureProfile

# Canonical default categories with the required exact keywords
DEFAULT_NATURE_CATEGORIES: Dict[str, NatureCategory] = {
    "rolling_hills_countryside": NatureCategory(
        id="rolling_hills_countryside",
        name="Rolling Hills & Countryside",
        description="Lush green rolling hills, aerial countryside landscapes, and golden hour slopes",
        keywords=[
            "cinematic rolling green hills",
            "aerial countryside scenery",
            "rolling green hills landscape",
            "peaceful green hills landscape",
            "green hills aesthetic video",
            "golden hour rolling hills",
            "dreamy countryside scenery",
        ],
    ),
    "mountains": NatureCategory(
        id="mountains",
        name="Mountains",
        description="Alpine peaks, misty valleys, and cinematic mountain vistas",
        keywords=[
            "peaceful mountains and valleys",
            "cinematic mountain landscape",
            "dreamy alpine mountains",
            "mountain clouds aesthetic",
            "scenic mountain valley",
            "misty mountain sunrise",
        ],
    ),
    "lakes_rivers": NatureCategory(
        id="lakes_rivers",
        name="Lakes and Rivers",
        description="Crystal clear alpine lakes, reflections, and peaceful flowing streams",
        keywords=[
            "peaceful rivers and lakes",
            "cinematic alpine lake",
            "mountain lake reflection",
            "peaceful flowing river",
            "dreamy river landscape",
            "crystal clear lake scenery",
        ],
    ),
    "sunsets_sunrises": NatureCategory(
        id="sunsets_sunrises",
        name="Sunsets and Sunrises",
        description="Warm golden hour landscapes, twilight skies, and glowing horizons",
        keywords=[
            "golden-hour landscapes",
            "sunset and sunrise landscapes",
            "cinematic golden hour landscape",
            "dreamy sunset clouds",
            "sunset over mountains",
            "peaceful sunrise scenery",
            "golden hour nature film",
        ],
    ),
    "forests_waterfalls": NatureCategory(
        id="forests_waterfalls",
        name="Forests and Waterfalls",
        description="Misty evergreen forests, cascading waterfalls, and lush woodland paths",
        keywords=[
            "forests, rivers and waterfalls",
            "misty evergreen forest",
            "cinematic waterfall scenery",
            "forest river aesthetic",
            "waterfall golden hour",
            "peaceful green forest landscape",
        ],
    ),
    "flowers_meadows": NatureCategory(
        id="flowers_meadows",
        name="Flowers and Meadows",
        description="Wildflower meadows, blooming alpine fields, and gentle spring scenery",
        keywords=[
            "meadows and flowers moving in the wind",
            "wildflower meadow cinematic",
            "flowers in golden sunlight",
            "dreamy spring landscape",
            "scenic flower field",
            "alpine meadow scenery",
        ],
    ),
}

DEFAULT_EXCLUDED_TERMS: List[str] = [
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
    "tiktok",
    "repost",
]


class ProfileManager:
    """Manages the Nature Cinematic Reels profile, category rotations, and query filtering."""

    def __init__(self, profile: Optional[NatureProfile] = None):
        self.profile = profile or NatureProfile(
            name="Nature Cinematic Reels",
            categories=list(DEFAULT_NATURE_CATEGORIES.keys()),
            excluded_terms=list(DEFAULT_EXCLUDED_TERMS),
            search_limit=15,
            daily_processing_limit=10,
            min_quality_score=65.0,
            is_active=True,
        )
        self._rotation_index: Dict[str, int] = {}

    def get_categories(self) -> Dict[str, NatureCategory]:
        """Return combined categories (default + any custom categories added)."""
        categories = dict(DEFAULT_NATURE_CATEGORIES)
        for cat_id, custom_kw in self.profile.custom_keywords.items():
            if cat_id in categories:
                # Merge custom keywords with default keywords without duplicates
                combined = list(dict.fromkeys(categories[cat_id].keywords + custom_kw))
                categories[cat_id] = NatureCategory(
                    id=cat_id,
                    name=categories[cat_id].name,
                    description=categories[cat_id].description,
                    keywords=combined,
                )
            else:
                # User defined custom category
                categories[cat_id] = NatureCategory(
                    id=cat_id,
                    name=cat_id.replace("_", " ").title(),
                    description=f"Custom nature category for {cat_id}",
                    keywords=custom_kw,
                )
        return categories

    def get_keywords_for_category(self, category_id: str) -> List[str]:
        """Get all configured keywords for a category."""
        categories = self.get_categories()
        cat = categories.get(category_id)
        return cat.keywords if cat else []

    def get_next_keyword(self, category_id: str, randomize: bool = False) -> Tuple[str, str]:
        """Return (category_id, keyword) rotated sequentially or picked randomly."""
        categories = self.get_categories()
        if category_id not in categories:
            category_id = random.choice(list(categories.keys())) if categories else "mountains"

        keywords = self.get_keywords_for_category(category_id)
        if not keywords:
            return category_id, "cinematic nature landscape"

        if randomize:
            chosen = random.choice(keywords)
        else:
            current_idx = self._rotation_index.get(category_id, 0)
            chosen = keywords[current_idx % len(keywords)]
            self._rotation_index[category_id] = (current_idx + 1) % len(keywords)

        return category_id, chosen

    def get_rotated_batch(self, count: int = 5, randomize: bool = True) -> List[Tuple[str, str]]:
        """Generate a balanced list of (category_id, keyword) across active categories."""
        active_cats = [c for c in self.profile.categories if c in self.get_categories()]
        if not active_cats:
            active_cats = list(self.get_categories().keys())

        batch: List[Tuple[str, str]] = []
        for i in range(count):
            cat_id = active_cats[i % len(active_cats)]
            cat_id, kw = self.get_next_keyword(cat_id, randomize=randomize)
            batch.append((cat_id, kw))
        return batch

    def is_title_or_desc_excluded(self, text: str) -> Tuple[bool, Optional[str]]:
        """Check if candidate text contains any excluded keywords."""
        if not text:
            return False, None
        lower_text = text.lower()
        for term in self.profile.excluded_terms:
            # Word boundary or simple containment check
            if term.lower() in lower_text:
                return True, f"Contains excluded term: '{term}'"
        return False, None
