"""Nature search profile manager with rotation, customization, and premium aesthetic keyword library."""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple

from nature.models import NatureCategory, NatureProfile, PreferredOrientation, RecencyPreference, SearchMood, SeasonPreference

# Canonical categories containing the exact required keywords
DEFAULT_NATURE_CATEGORIES: Dict[str, NatureCategory] = {
    # 1. Autumn Forest Aesthetic
    "autumn_forest": NatureCategory(
        id="autumn_forest",
        name="Autumn Forest Aesthetic",
        description="Dreamy fall forests, golden leaves, misty walking trails, and cozy autumn scenery",
        keywords=[
            "aesthetic autumn forest cinematic video",
            "dreamy fall forest golden leaves",
            "misty autumn forest walking trail",
            "orange and red autumn leaves falling",
            "cozy fall forest aesthetic 4K",
            "autumn woodland fog sunrise",
            "cinematic fall foliage river",
            "golden autumn trees in soft sunlight",
            "peaceful autumn forest POV",
            "fall forest wind blowing leaves",
            "moody autumn woods cinematic footage",
            "enchanted fall forest scenery",
            "autumn forest rain aesthetic",
            "orange maple leaves close-up cinematic",
            "autumn forest drone footage",
            "autumn lake surrounded by colorful trees",
            "fall foliage mountain valley",
            "golden leaves forest road cinematic",
        ],
        icon="Flame",
    ),
    # 2. Misty Mountains & Mountain Valleys
    "misty_mountains": NatureCategory(
        id="misty_mountains",
        name="Misty Mountains & Mountain Valleys",
        description="Cinematic misty peaks, clouds above valleys, alpine lakes, and dramatic ridges",
        keywords=[
            "cinematic misty mountain landscape video",
            "dreamy mountains above clouds",
            "fog rolling through green mountain valleys",
            "mountain peaks at golden hour",
            "peaceful alpine mountain lake cinematic",
            "moody mountains under cloudy sky",
            "mountain meadow wildflowers wind",
            "mountain ridge sunrise timelapse",
            "dramatic mountain clouds moving",
            "lush green mountain valley 4K footage",
            "misty pine forest mountain aesthetic",
            "mountain road through fog cinematic",
            "snow capped mountains reflection lake",
            "aerial mountain landscape cinematic drone",
            "mountain waterfall hidden forest",
            "remote mountain cabin nature scenery",
            "emerald mountains after rain",
            "cinematic mountain landscape vertical video",
        ],
        icon="Mountain",
    ),
    # 3. Forests, Moss & Rain
    "forests_moss_rain": NatureCategory(
        id="forests_moss_rain",
        name="Forests, Moss & Rain",
        description="Mossy ancient woods, lush green rain-soaked forests, sun rays, and peaceful streams",
        keywords=[
            "mossy forest cinematic aesthetic",
            "lush green forest after rain",
            "misty pine forest morning fog",
            "enchanted woodland sun rays",
            "peaceful forest stream 4K video",
            "rain falling through forest trees",
            "dreamy fern forest close-up",
            "dark green forest cinematic footage",
            "forest canopy moving in the wind",
            "woodland path soft morning light",
            "moss covered rocks flowing stream",
            "ancient forest fog aesthetic",
            "forest sunlight rays volumetric light",
            "peaceful forest POV walking video",
            "lush rainforest waterfall cinematic",
            "forest reflections in calm water",
        ],
        icon="Trees",
    ),
    # 4. Lakes, Rivers & Waterfalls
    "lakes_rivers_waterfalls": NatureCategory(
        id="lakes_rivers_waterfalls",
        name="Lakes, Rivers & Waterfalls",
        description="Turquoise alpine lakes, mirror reflections, slow flowing rivers, and hidden waterfalls",
        keywords=[
            "turquoise alpine lake cinematic video",
            "mountain lake mirror reflection",
            "peaceful river flowing through autumn forest",
            "waterfall surrounded by green forest",
            "slow flowing river aesthetic nature",
            "river rocks crystal clear water",
            "hidden waterfall mossy rocks",
            "lake mist at sunrise cinematic",
            "autumn lake golden reflections",
            "aerial river winding through mountains",
            "dreamy lake mountains clouds reflection",
            "long exposure waterfall nature aesthetic",
            "peaceful lakeside trees moving in wind",
            "cinematic forest creek close up",
        ],
        icon="Waves",
    ),
    # 5. Golden Hour, Sunsets & Sunrises
    "golden_hour_sunsets": NatureCategory(
        id="golden_hour_sunsets",
        name="Golden Hour, Sunsets & Sunrises",
        description="Dreamy golden hour slopes, pastel twilight skies, and glowing mountain horizons",
        keywords=[
            "dreamy golden hour mountain landscape",
            "cinematic sunset over rolling green hills",
            "sunrise mist over forest valley",
            "warm sunlight through pine forest",
            "golden hour wildflower meadow",
            "sunset clouds over mountain peaks",
            "peaceful sun rays through autumn trees",
            "orange pink sky mountain lake reflection",
            "cinematic sunrise over ocean cliffs",
            "dreamy countryside sunset aesthetic",
            "golden light illuminating foggy forest",
            "sunset through trees slow cinematic footage",
            "pastel sky over alpine mountains",
            "morning light over green valley",
        ],
        icon="Sun",
    ),
    # 6. Meadows, Flowers & Countryside
    "meadows_flowers": NatureCategory(
        id="meadows_flowers",
        name="Meadows, Flowers & Countryside",
        description="Wildflowers in morning light, rolling green hills, lavender breezes, and gentle countryside",
        keywords=[
            "dreamy wildflower meadow cinematic",
            "alpine meadow flowers mountain background",
            "tall grass moving in sunset wind",
            "peaceful countryside rolling hills",
            "wildflowers in soft morning light",
            "cinematic lavender field breeze",
            "green hills under dramatic clouds",
            "flower field golden hour aesthetic",
            "spring meadow mountain landscape",
            "scenic countryside road cinematic",
            "slow motion flowers in gentle wind",
            "foggy meadow sunrise nature footage",
        ],
        icon="Flower2",
    ),
    # 7. Snow, Winter & Moody Nature
    "snow_winter": NatureCategory(
        id="snow_winter",
        name="Snow, Winter & Moody Nature",
        description="Snowy pine woods, frozen alpine lakes, winter cabins, and blue hour mountain scenery",
        keywords=[
            "snowy pine forest cinematic aesthetic",
            "peaceful winter forest snowfall",
            "frozen alpine lake mountain scenery",
            "foggy winter mountain landscape",
            "snow covered trees soft morning light",
            "winter cabin forest cinematic footage",
            "misty snowy mountain valley",
            "quiet winter woodland trail",
            "snow falling through pine forest",
            "blue hour snowy mountain lake",
        ],
        icon="CloudSnow",
    ),
    # 8. Rare & Premium Nature Discoveries
    "rare_premium": NatureCategory(
        id="rare_premium",
        name="Rare & Premium Nature Discoveries",
        description="Untouched wilderness, remote valleys, aerial drone vistas, and ethereal landscapes",
        keywords=[
            "untouched wilderness cinematic footage",
            "remote alpine valley aerial video",
            "hidden forest waterfall aesthetic",
            "dramatic clouds moving over green mountains",
            "cinematic nature drone footage 4K",
            "peaceful remote lake surrounded by forest",
            "atmospheric woodland landscape film",
            "dreamy nature scenery without people",
            "cinematic river valley from above",
            "unique nature landscape slow footage",
            "quiet wilderness golden hour film",
            "ethereal foggy landscape aesthetic",
        ],
        icon="Sparkles",
    ),
    # Legacy categories kept for backwards compatibility with existing databases & tests
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
            "cinematic misty mountain landscape video",
            "fog rolling through green mountain valleys",
        ],
        icon="Mountain",
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
            "turquoise alpine lake cinematic video",
        ],
        icon="Waves",
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
        icon="Sun",
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
        icon="Trees",
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
        icon="Flower2",
    ),
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
        icon="Compass",
    ),
}

# Category normalization mapping
CATEGORY_ALIASES: Dict[str, str] = {
    "autumn": "autumn_forest",
    "fall": "autumn_forest",
    "autumn_forest": "autumn_forest",
    "mountains": "misty_mountains",
    "mountain": "misty_mountains",
    "misty_mountains": "misty_mountains",
    "valleys": "misty_mountains",
    "forest": "forests_moss_rain",
    "forests": "forests_moss_rain",
    "rain": "forests_moss_rain",
    "moss": "forests_moss_rain",
    "forests_moss_rain": "forests_moss_rain",
    "lakes": "lakes_rivers_waterfalls",
    "lake": "lakes_rivers_waterfalls",
    "rivers": "lakes_rivers_waterfalls",
    "river": "lakes_rivers_waterfalls",
    "waterfalls": "lakes_rivers_waterfalls",
    "waterfall": "lakes_rivers_waterfalls",
    "lakes_rivers": "lakes_rivers_waterfalls",
    "lakes_rivers_waterfalls": "lakes_rivers_waterfalls",
    "sunsets": "golden_hour_sunsets",
    "sunset": "golden_hour_sunsets",
    "sunrise": "golden_hour_sunsets",
    "sunrises": "golden_hour_sunsets",
    "golden_hour": "golden_hour_sunsets",
    "sunsets_sunrises": "golden_hour_sunsets",
    "golden_hour_sunsets": "golden_hour_sunsets",
    "meadows": "meadows_flowers",
    "meadow": "meadows_flowers",
    "flowers": "meadows_flowers",
    "flower": "meadows_flowers",
    "flowers_meadows": "meadows_flowers",
    "meadows_flowers": "meadows_flowers",
    "countryside": "meadows_flowers",
    "rolling_hills": "meadows_flowers",
    "rolling_hills_countryside": "meadows_flowers",
    "snow": "snow_winter",
    "winter": "snow_winter",
    "snow_winter": "snow_winter",
    "rare": "rare_premium",
    "premium": "rare_premium",
    "wilderness": "rare_premium",
    "rare_premium": "rare_premium",
}

DEFAULT_EXCLUDED_TERMS: List[str] = [
    # Anime, Cartoon, CGI, Still Illustrations
    "anime",
    "cartoon",
    "illustration",
    "manga",
    "drawing",
    "sketch",
    "digital art",
    "ai generated",
    "midjourney",
    "stable diffusion",
    "dall-e",
    "blender 3d",
    "cgi",
    "render",
    "animated",
    "comic",
    # Commercial, Fashion, Beauty & Makeup
    "fashion",
    "outfit",
    "makeup",
    "beauty",
    "cosmetics",
    "skincare",
    "hair tutorial",
    "shopping",
    "haul",
    "unboxing",
    "product",
    "commercial",
    "advertisement",
    "promo",
    "recipe",
    "cooking",
    "kitchen",
    "gym",
    "workout",
    "fitness",
    # Gaming & Social Memes
    "gaming",
    "gameplay",
    "minecraft",
    "fortnite",
    "roblox",
    "dance",
    "tiktok dance",
    "vlog",
    "interview",
    "podcast",
    "meme",
    # Watermarks & Overlays
    "watermark",
    "repost",
    "@tiktok",
    "tiktok.com",
    "capcut",
    "douyin",
    # Urban & Traffic
    "bedroom",
    "living room",
    "interior design",
    "office",
    "car interior",
    "traffic",
    "highway cars",
]


class ProfileManager:
    """Manages Nature search profiles, aesthetic keyword libraries, rotations, and smart queries."""

    def __init__(self, profile: Optional[NatureProfile] = None):
        self.profile = profile or NatureProfile(
            name="Nature Cinematic Reels",
            categories=[
                "autumn_forest",
                "misty_mountains",
                "forests_moss_rain",
                "lakes_rivers_waterfalls",
                "golden_hour_sunsets",
                "meadows_flowers",
                "snow_winter",
                "rare_premium",
            ],
            excluded_terms=list(DEFAULT_EXCLUDED_TERMS),
            search_limit=15,
            daily_processing_limit=10,
            min_quality_score=65.0,
            recency_preference="any",
            strict_recency=False,
            search_mood="cinematic",
            season="any",
            preferred_orientation="vertical_9_16",
            is_active=True,
        )
        self._rotation_index: Dict[str, int] = {}
        self._keyword_failures: Dict[str, int] = {}

    def normalize_category_id(self, category_id: str) -> str:
        """Resolve category aliases to standard category ID."""
        if not category_id:
            return "autumn_forest"
        low = category_id.lower().strip()
        return CATEGORY_ALIASES.get(low, low)

    def get_categories(self) -> Dict[str, NatureCategory]:
        """Return combined categories (default + any custom categories added)."""
        categories = dict(DEFAULT_NATURE_CATEGORIES)
        for cat_id, custom_kw in self.profile.custom_keywords.items():
            if cat_id in categories:
                combined = list(dict.fromkeys(categories[cat_id].keywords + custom_kw))
                categories[cat_id] = NatureCategory(
                    id=cat_id,
                    name=categories[cat_id].name,
                    description=categories[cat_id].description,
                    keywords=combined,
                    icon=categories[cat_id].icon,
                )
            else:
                categories[cat_id] = NatureCategory(
                    id=cat_id,
                    name=cat_id.replace("_", " ").title(),
                    description=f"Custom nature category for {cat_id}",
                    keywords=custom_kw,
                    icon="Compass",
                )
        return categories

    def get_keywords_for_category(self, category_id: str) -> List[str]:
        """Get all configured keywords for a category."""
        resolved = self.normalize_category_id(category_id)
        categories = self.get_categories()
        cat = categories.get(resolved) or categories.get(category_id)
        return cat.keywords if cat else []

    def get_next_keyword(self, category_id: str, randomize: bool = False) -> Tuple[str, str]:
        """Return (category_id, keyword) rotated sequentially or picked with failure penalty."""
        categories = self.get_categories()
        resolved = category_id if category_id in categories else self.normalize_category_id(category_id)
        if resolved not in categories:
            resolved = "autumn_forest" if "autumn_forest" in categories else list(categories.keys())[0]

        keywords = self.get_keywords_for_category(resolved)
        if not keywords:
            return resolved, "cinematic nature landscape vertical video"

        if randomize:
            # Sort/weight candidates so keywords with lower failure counts are favored
            weights = [max(1, 10 - self._keyword_failures.get(kw, 0) * 3) for kw in keywords]
            chosen = random.choices(keywords, weights=weights, k=1)[0]
        else:
            current_idx = self._rotation_index.get(resolved, 0)
            chosen = keywords[current_idx % len(keywords)]
            self._rotation_index[resolved] = (current_idx + 1) % len(keywords)

        return resolved, chosen

    def generate_search_query(
        self,
        category_id: str,
        keyword: Optional[str] = None,
        mood: Optional[str] = None,
        season: Optional[str] = None,
        orientation: Optional[str] = None,
        randomize: bool = False,
    ) -> Tuple[str, str, str]:
        """Generate a balanced, high-yield Pinterest video search query.

        Returns (resolved_category, base_keyword, formatted_search_query).
        """
        resolved_cat = self.normalize_category_id(category_id)
        if not keyword:
            resolved_cat, base_kw = self.get_next_keyword(resolved_cat, randomize=randomize)
        else:
            base_kw = keyword

        query_tokens = base_kw.lower().split()
        all_moods = {"cinematic", "dreamy", "peaceful", "moody", "cozy", "dramatic"}

        # 1. Blend Mood if specified and not redundant (replace existing mood instead of stacking)
        effective_mood = (mood or self.profile.search_mood or "any").lower().strip()
        if effective_mood and effective_mood != "any":
            replaced = False
            for idx, tok in enumerate(query_tokens):
                if tok in all_moods:
                    query_tokens[idx] = effective_mood
                    replaced = True
                    break
            if not replaced and effective_mood not in query_tokens:
                query_tokens.insert(0, effective_mood)

        # 2. Blend Season if specified and not redundant
        effective_season = (season or self.profile.season or "any").lower().strip()
        seasonal_synonyms = {
            "autumn": ["autumn", "fall"],
            "winter": ["winter", "snow", "snowy"],
            "spring": ["spring", "bloom", "blooming"],
            "summer": ["summer", "sunlit"],
        }
        if effective_season and effective_season != "any":
            syns = seasonal_synonyms.get(effective_season, [effective_season])
            has_season = any(s in query_tokens for s in syns)
            if not has_season:
                insert_idx = 1 if len(query_tokens) > 1 and query_tokens[0] == effective_mood else 0
                query_tokens.insert(insert_idx, effective_season)

        # 3. Ensure video qualifier is present so Pinterest returns video Pins
        has_video_term = any(v in query_tokens for v in ["video", "footage", "timelapse", "drone", "pov", "clip"])
        effective_orient = (orientation or self.profile.preferred_orientation or "vertical_9_16").lower().strip()

        if not has_video_term:
            if effective_orient == "vertical_9_16" and "vertical" not in query_tokens:
                query_tokens.append("vertical video")
            else:
                query_tokens.append("video")

        # 4. Remove redundant filler words that overconstrain Pinterest search when token count > 5
        fillers = ["scenery", "landscape", "nature", "4k", "aesthetic"]
        if len(query_tokens) > 5:
            filtered = []
            for t in query_tokens:
                if t in fillers and (len(query_tokens) - len(fillers) + len(filtered)) >= 3:
                    continue
                filtered.append(t)
            if len(filtered) >= 3:
                query_tokens = filtered

        final_query = " ".join(query_tokens)
        return resolved_cat, base_kw, final_query

    def record_keyword_result(self, keyword: str, eligible_videos_found: int) -> None:
        """Track keyword performance to deprioritize dry searches."""
        if eligible_videos_found == 0:
            self._keyword_failures[keyword] = self._keyword_failures.get(keyword, 0) + 1
        else:
            self._keyword_failures[keyword] = max(0, self._keyword_failures.get(keyword, 0) - 1)

    def is_title_or_desc_excluded(self, text: str) -> Tuple[bool, Optional[str]]:
        """Check if candidate text contains prohibited content without falsely rejecting nature footage."""
        if not text:
            return False, None
        lower_text = text.lower()

        # Hard-rejection patterns: anime, gaming, shopping, makeup, cartoons, watermarks
        hard_terms = [
            "anime",
            "cartoon",
            "illustration",
            "manga",
            "drawing",
            "sketch",
            "digital art",
            "ai generated",
            "midjourney",
            "stable diffusion",
            "blender 3d",
            "cgi",
            "comic",
            "gaming",
            "gameplay",
            "minecraft",
            "fortnite",
            "roblox",
            "makeup",
            "cosmetics",
            "skincare",
            "hair tutorial",
            "shopping",
            "unboxing",
            "recipe",
            "cooking",
            "gym workout",
            "tiktok dance",
            "meme",
            "watermark",
            "repost",
            "@tiktok",
            "capcut",
            "douyin",
            # Fiction & Action Movies
            "sci-fi",
            "scifi",
            "action movie",
            "movie trailer",
            "dinosaur",
            "dinosaurier",
            "spaceship",
            "cyberpunk",
            "superhero",
        ]
        for term in hard_terms:
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, lower_text):
                return True, f"Contains excluded term: '{term}'"

        # Profile-configured excluded terms with semantic protection
        for term in self.profile.excluded_terms:
            term_lower = term.lower()
            # Special protection: "person" or "people" in title shouldn't reject genuine nature footage
            if term_lower in ("person", "people", "man", "woman"):
                if re.search(r"\b(talking to camera|face|portrait|selfie|vlog|interview|podcast)\b", lower_text):
                    return True, f"Focuses on people/vlog rather than pure scenic nature: '{term}'"
                continue
            # Special protection: "text" or "quote" in title shouldn't reject scenic footage with quote caption
            if term_lower in ("text", "quote"):
                if re.search(r"\b(quote card|typography poster|quote template|text animation)\b", lower_text):
                    return True, f"Video is a quote graphic rather than nature footage: '{term}'"
                continue

            pattern = r"\b" + re.escape(term_lower) + r"\b"
            if re.search(pattern, lower_text):
                return True, f"Contains excluded term: '{term}'"

        return False, None
