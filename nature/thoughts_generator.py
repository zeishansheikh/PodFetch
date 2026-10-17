"""AI-powered poetic thoughts, captions, and hashtag generator with repetition protection."""

from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Any, Dict, List, Optional

import requests
from nature.models import NatureThought
from quran.key_rotator import get_key_rotator

logger = logging.getLogger(__name__)

GROQ_CHAT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_AI_MODEL = "openai/gpt-oss-20b"
FALLBACK_AI_MODEL = "openai/gpt-oss-120b"

# High-quality deterministic fallback thoughts by category (4-7 line philosophical reflections)
CURATED_FALLBACK_THOUGHTS: Dict[str, List[Dict[str, Any]]] = {
    "rolling_hills_countryside": [
        {
            "thought": "The older you get,\nthe simpler life becomes:\nQuiet morning air.\nRolling green hills.\nPeace in your own skin.\nAnd nowhere you need to rush.",
            "caption": "Simplicity is the truest luxury. Give yourself time to breathe and stand where the wind is quiet.",
            "hashtags": ["#countrysidewalks", "#rollinggreenhills", "#simplelife", "#peaceandcalm"],
            "theme": "growing_older_and_gaining_perspective",
        },
        {
            "thought": "As the years move on,\nyou learn what truly matters:\nGentle mornings.\nUnspoken understanding.\nTime spent in the wild.\nAnd a quiet, grateful heart.",
            "caption": "Life softens when we stop chasing noise. Finding peace across open fields and sunlit slopes.",
            "hashtags": ["#gentleliving", "#naturetherapy", "#countrysidelife", "#innerpeace"],
            "theme": "gratitude_and_happiness",
        },
        {
            "thought": "The hills do not compete,\nyet they carry the sky.\nLeave behind the hurry.\nBreathe in the stillness,\nand let today be enough.",
            "caption": "There is nothing to prove to the wind. Let today unfold at its own steady pace.",
            "hashtags": ["#calmmind", "#scenicviews", "#slowdown", "#naturelovers"],
            "theme": "peace_and_simplicity",
        },
    ],
    "mountains": [
        {
            "thought": "In the silence of the peaks,\nwisdom comes slowly:\nClimb without comparison.\nRest without guilt.\nStand tall through the storm.\nAnd cherish every quiet view.",
            "caption": "Quiet elevation. Allow yourself the grace to find strength at your own steady pace.",
            "hashtags": ["#mountainviews", "#cinematicnature", "#peaceandquiet", "#solitude"],
            "theme": "growth_and_patience",
        },
        {
            "thought": "The greatest journey\nis not to conquer summits,\nbut to find stillness\nin the middle of the climb.",
            "caption": "Standing among giants. Every meaningful journey is built from quiet, steady persistence.",
            "hashtags": ["#alpinelife", "#mountaintherapy", "#natureescape", "#clarity"],
            "theme": "hope_and_resilience",
        },
    ],
    "lakes_rivers": [
        {
            "thought": "Like water finding the sea,\nlife teaches one truth:\nDo not force what is meant to flow.\nStillness brings clarity.\nAnd peace is a choice\nyou make every day.",
            "caption": "Still waters and gentle currents. Let go of what resists and flow naturally.",
            "hashtags": ["#lakeview", "#peacefulriver", "#naturecinematics", "#stillness"],
            "theme": "life_lessons_and_letting_go",
        },
        {
            "thought": "Calm waters reflect\nthe clearest sky.\nWhen the heart settles,\nthe path ahead\nbecomes simple again.",
            "caption": "When the mind becomes still, the world around us regains its natural beauty.",
            "hashtags": ["#alpinelake", "#reflectionshot", "#purenature", "#innercalm"],
            "theme": "peace_and_simplicity",
        },
    ],
    "sunsets_sunrises": [
        {
            "thought": "With every passing day,\nthe heart learns softness:\nLet the sun go down.\nRelease what was heavy.\nTomorrow is waiting,\nunwritten and clear.",
            "caption": "Golden light fading into twilight. Tomorrow begins with fresh promise.",
            "hashtags": ["#goldenhour", "#sunsetlandscape", "#eveningglow", "#gratitude"],
            "theme": "quiet_moments_and_appreciating_the_present",
        },
        {
            "thought": "Light returns gently,\nnever asking for permission.\nEvery dawn is an invitation\nto begin again\nwith softer hands\nand a lighter heart.",
            "caption": "A new horizon. Start today without carrying yesterday's weight.",
            "hashtags": ["#sunrisemagic", "#dawnpatrol", "#naturefilm", "#freshstart"],
            "theme": "hope_and_resilience",
        },
    ],
    "forests_waterfalls": [
        {
            "thought": "Walk gently beneath the pines.\nNature does not argue with time.\nIt grows in patience.\nIt heals in silence.\nAnd so can you.",
            "caption": "Lost in the emerald canopy. Nature never rushes, yet everything is accomplished.",
            "hashtags": ["#forestmagic", "#waterfallphotography", "#greenery", "#serenity"],
            "theme": "nature_and_healing",
        },
        {
            "thought": "Roots grow deep in silence\nbefore branches reach the sky.\nTrust the quiet seasons.\nNothing in nature blooms\nall year long.",
            "caption": "Deep in the pines. True strength is nurtured quietly beneath the surface.",
            "hashtags": ["#mistyforest", "#ancienttrees", "#woodland", "#slowliving"],
            "theme": "growth_and_patience",
        },
    ],
    "flowers_meadows": [
        {
            "thought": "The meadow asks for nothing\nexcept the wind and sun.\nTo bloom without hurry,\nto rest in the warmth,\nand to trust your own season.",
            "caption": "Wildflowers dancing in the mountain breeze. Beauty thrives in simple, untamed places.",
            "hashtags": ["#wildflowermeadow", "#springscenery", "#bloomwhereyouare", "#gentlelife"],
            "theme": "happiness_and_gratitude",
        },
        {
            "thought": "Happiness is not complicated:\nA breath of fresh air.\nSunlight through the leaves.\nAnd knowing that who you are\nis already enough.",
            "caption": "Golden sunlight over open fields. Treasure the quiet, uncomplicated moments.",
            "hashtags": ["#meadowview", "#goldenlight", "#earthtones", "#peacefulmoments"],
            "theme": "peace_and_simplicity",
        },
    ],
}


def extract_json_from_llm(raw: str) -> Dict[str, Any]:
    """Robustly extract and parse JSON payload from LLM responses."""
    cleaned = raw.strip()
    # Strip markdown block wrappers ```json ... ```
    if cleaned.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start : end + 1]
            return json.loads(snippet)
        raise ValueError(f"Could not parse valid JSON from LLM output:\n{raw[:300]}")


class NatureThoughtsGenerator:
    """Generates original, emotionally resonant thoughts and captions for nature footage."""

    def __init__(self, model_name: str = DEFAULT_AI_MODEL):
        self.model_name = model_name
        self.rotator = get_key_rotator()

    def generate_thought_and_caption(
        self,
        category: str,
        keyword: str,
        past_thoughts: Optional[List[str]] = None,
        creator_attribution: Optional[str] = None,
    ) -> NatureThought:
        """Generate original thought, caption, and hashtags using Groq LLM,

        with automatic fallback to curated library if AI service is unavailable.
        """
        past_thoughts = past_thoughts or []
        # Check if we have active Groq API keys
        if not self.rotator.has_keys:
            logger.info("No active Groq API key found. Using deterministic curated thought library.")
            return self._get_fallback_thought(category, past_thoughts, creator_attribution)

        # Build prompt
        past_sample = "\n".join(f"- \"{t.replace(chr(10), ' ')}\"" for t in past_thoughts[-15:])
        system_prompt = (
            "You are a poetic, introspective nature filmmaker and writer creating calm, minimalist Reel text.\n"
            "Your aesthetic is quiet, elegant, deeply grounded, and emotionally resonant.\n"
            "Generate ONE short, original on-screen thought arranged in 4-7 readable lines, an accompanying social caption, and 3-5 specific hashtags.\n\n"
            "CRITICAL RULES:\n"
            "1. ON-SCREEN THOUGHT: A short, original inspirational or philosophical nature reflection, arranged in approximately 4 to 7 readable lines separated by newlines (\\n). Each line should be short (2 to 5 words), natural, and comfortable to read on vertical video. Total length: 15-32 words.\n"
            "2. NO REPETITION: Do NOT repeat or paraphrase any of these recently used thoughts:\n"
            f"{past_sample if past_sample else '(none yet)'}\n"
            "3. NO QUOTES FROM FAMOUS PEOPLE: All thoughts must be completely original reflections. Never attribute AI-generated text to a real author.\n"
            "4. THEMES: Peace and simplicity, nature and healing, growing older and gaining perspective, gratitude and happiness, life lessons and letting go, or quiet moments and appreciating the present.\n"
            "5. HASHTAGS: Exactly 3 to 5 focused hashtags directly relevant to the specific nature category. No generic spam (#viral, #fyp, #trending are forbidden).\n"
            "6. JSON FORMAT ONLY: Respond strictly with a JSON object matching the requested schema.\n\n"
            "JSON SCHEMA:\n"
            "{\n"
            '  "thought_text": "Line one\\nline two\\nline three\\nline four\\nline five",\n'
            '  "caption": "A thoughtful 1-2 sentence caption expanding gently on the scene.",\n'
            '  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4"],\n'
            '  "title_hook": "Optional short calm title",\n'
            '  "alternative_caption": "Optional alternate caption",\n'
            '  "theme": "growing_older_and_gaining_perspective"\n'
            "}"
        )

        user_prompt = f"Footage category: '{category}'. Discovery search phrase: '{keyword}'."

        for model in [self.model_name, FALLBACK_AI_MODEL]:
            for attempt in range(2):
                try:
                    api_key = self.rotator.get_current_key()
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.7,
                        "max_tokens": 2048,
                    }

                    resp = requests.post(GROQ_CHAT_ENDPOINT, headers=headers, json=payload, timeout=25)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                        parsed = extract_json_from_llm(content)

                        thought_text = str(parsed.get("thought_text", "")).strip().replace("—", " - ")
                        caption = str(parsed.get("caption", "")).strip().replace("—", " - ")
                        tags = [str(t).strip() for t in parsed.get("hashtags", []) if str(t).strip().startswith("#")]
                        if not tags:
                            tags = [f"#{category.replace('_', '')}", "#naturecinematic", "#quietmoments"]

                        # Check for repetition
                        is_duplicate = any(
                            thought_text.lower().replace("\n", " ") == pt.lower().replace("\n", " ")
                            for pt in past_thoughts
                        )
                        if is_duplicate:
                            logger.info("AI generated thought was duplicate of past entry; rotating...")
                            continue

                        return NatureThought(
                            thought_text=thought_text,
                            caption=caption,
                            hashtags=tags[:5],
                            title_hook=parsed.get("title_hook"),
                            source_attribution=creator_attribution,
                            alternative_caption=parsed.get("alternative_caption"),
                            theme=parsed.get("theme", "peace_and_solitude"),
                            ai_provider="groq",
                            model_name=model,
                            is_fallback=False,
                        )
                    elif resp.status_code in (401, 429):
                        self.rotator.rotate_key(reason=f"Status code {resp.status_code}")
                    else:
                        logger.warning(f"Groq API returned HTTP {resp.status_code}: {resp.text[:200]}")
                except Exception as e:
                    logger.warning(f"Groq API call attempt {attempt+1} failed: {e}")
                    self.rotator.rotate_key(reason=str(e))

        # Fallback to curated library if all attempts fail
        logger.info("Falling back to curated library for nature thoughts.")
        return self._get_fallback_thought(category, past_thoughts, creator_attribution)

    def _get_fallback_thought(
        self,
        category: str,
        past_thoughts: List[str],
        creator_attribution: Optional[str] = None,
    ) -> NatureThought:
        """Select a non-repetitive thought from the curated fallback collection."""
        cat_key = category if category in CURATED_FALLBACK_THOUGHTS else "mountains"
        pool = CURATED_FALLBACK_THOUGHTS[cat_key]

        # Filter out any thoughts already present in past_thoughts
        past_clean = [pt.lower().replace("\n", " ") for pt in past_thoughts]
        available = [item for item in pool if item["thought"].lower().replace("\n", " ") not in past_clean]

        choice = random.choice(available if available else pool)

        return NatureThought(
            thought_text=choice["thought"],
            caption=choice["caption"],
            hashtags=choice["hashtags"],
            title_hook="Quiet Moment in Nature",
            source_attribution=creator_attribution,
            theme=choice["theme"],
            ai_provider="curated_library",
            model_name="curated-fallback-engine",
            is_fallback=True,
        )
