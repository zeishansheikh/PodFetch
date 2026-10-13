"""Ayah selection module using Groq LLM (openai/gpt-oss-20b).
Analyzes timestamped transcript segments to select standalone, spiritually meaningful ayat
with universal themes (patience, gratitude, hope, mercy, trust in Allah) per Contract Section 6, Step 4.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from logger import get_logger
from quran.key_rotator import get_key_rotator
from quran.transcribe import TranscriptSegment

logger = get_logger("quran_selector")

GROQ_CHAT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
PRIMARY_MODEL = "openai/gpt-oss-20b"
FALLBACK_MODEL = "openai/gpt-oss-120b"


@dataclass
class SelectedAyahCandidate:
    """LLM candidate selection with timestamps and reasoning."""

    chosen_arabic: str
    surah_hint: Optional[int]
    ayah_hint: Optional[int]
    start_time: float
    end_time: float
    reason: str
    english_caption: str
    urdu_translation: Optional[str] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


SYSTEM_PROMPT = """You are an expert Quran scholar and Islamic audio editor.
You will be given timestamped transcript segments of a Quran recitation (often containing Arabic recitation followed by Urdu translation).

Your task is to select ONE standalone, deeply meaningful Ayah (or 2-3 short contiguous ones) suitable for a short-form spiritual reel.

CRITICAL RULES:
1. STANDALONE ONLY: The selected verse MUST convey complete, self-contained meaning without needing prior or following verses.
2. UNIVERSAL THEMES: Prioritize themes of patience (sabr), gratitude (shukr), divine mercy, hope, trust in Allah (tawakkul), remembrance (dhikr), and peace of the heart.
3. REJECT CONTEXT-DEPENDENT: REJECT verses with dangling pronouns ("And when they said...", "So he said..."), mid-passage legal rulings, specific historical battles, or incomplete thoughts.
4. TIMESTAMPS: start_time MUST mark the start of the Arabic recitation of this ayah. end_time MUST mark the conclusion of the corresponding Urdu translation of this ayah. The duration (end_time - start_time) should be between 8 and 38 seconds.
5. NO EM-DASH: Never use the em-dash character ("—") or en-dash ("–") in your reason, english_caption, or any output string. Use hyphens or commas instead.
6. JSON ONLY: Respond ONLY with a valid JSON object matching the requested schema.

JSON SCHEMA:
{
  "chosen_arabic": "Arabic text of the verse from transcript",
  "surah_hint": 2,
  "ayah_hint": 255,
  "start_time": 10.5,
  "end_time": 28.3,
  "reason": "Complete spiritual meaning about patience and reliance upon God",
  "english_caption": "A gentle reminder that with patience comes divine ease.",
  "urdu_translation": "Urdu translation text if heard in transcript"
}
"""


def extract_json_from_llm(content_str: str) -> Dict[str, Any]:
    """Parse JSON safely from raw response or markdown code blocks."""
    cleaned = content_str.strip()
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback regex search for outer braces
        brace_match = re.search(r"(\{[\s\S]*\})", cleaned)
        if brace_match:
            return json.loads(brace_match.group(1))
        raise


def select_best_ayah(
    segments: List[TranscriptSegment],
    surah_name_hint: Optional[str] = None,
    max_retries: int = 3,
) -> SelectedAyahCandidate:
    """Call Groq LLM to pick the best standalone ayah candidate covering recitation + translation."""
    rotator = get_key_rotator()

    # Format segments for LLM
    formatted_transcript = []
    for s in segments:
        formatted_transcript.append({
            "start": round(s.start, 2),
            "end": round(s.end, 2),
            "text": s.text,
        })

    user_content = {
        "video_context": f"Surah or video hint: {surah_name_hint or 'Quran recitation with translation'}",
        "segments": formatted_transcript[:120],  # cap to reasonable token limit
    }

    last_error: Optional[Exception] = None

    for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
        for attempt in range(max_retries):
            api_key = rotator.get_current_key()
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Please respond with a valid JSON object matching the schema. Here is the timestamped transcript:\n{json.dumps(user_content, ensure_ascii=False)}",
                    },
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
            }

            try:
                logger.info(f"Querying Groq LLM ({model_name}) for standalone Ayah selection...")
                resp = requests.post(
                    GROQ_CHAT_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=60,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    content_str = data["choices"][0]["message"]["content"]
                    parsed = extract_json_from_llm(content_str)

                    # Clean em-dashes from any string in parsed
                    caption = str(parsed.get("english_caption", "")).replace("—", " - ").replace("–", " - ").strip()
                    reason = str(parsed.get("reason", "")).replace("—", " - ").replace("–", " - ").strip()

                    candidate = SelectedAyahCandidate(
                        chosen_arabic=str(parsed.get("chosen_arabic", "")).strip(),
                        surah_hint=int(parsed["surah_hint"]) if parsed.get("surah_hint") else None,
                        ayah_hint=int(parsed["ayah_hint"]) if parsed.get("ayah_hint") else None,
                        start_time=float(parsed.get("start_time", 0.0)),
                        end_time=float(parsed.get("end_time", 0.0)),
                        reason=reason,
                        english_caption=caption,
                        urdu_translation=parsed.get("urdu_translation"),
                    )

                    # Validation
                    if candidate.duration < 5.0:
                        logger.warning(
                            f"LLM returned too short duration ({candidate.duration:.1f}s), adjusting..."
                        )
                        candidate.end_time = candidate.start_time + 15.0

                    logger.info(
                        f"Ayah selected: Surah {candidate.surah_hint}:{candidate.ayah_hint} "
                        f"({candidate.start_time:.1f}s to {candidate.end_time:.1f}s, duration: {candidate.duration:.1f}s)"
                    )
                    return candidate

                if resp.status_code in (429, 401):
                    err_msg = f"HTTP {resp.status_code}: {resp.text}"
                    rotator.rotate_key(reason=f"LLM API error: {err_msg}")
                    time.sleep(1.0)
                    continue

                if resp.status_code == 404 and "model" in resp.text.lower():
                    logger.warning(f"Model {model_name} not available, switching to fallback...")
                    break

                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

            except Exception as e:
                last_error = e
                logger.warning(f"Ayah selection attempt {attempt + 1} with {model_name} failed: {e}")
                rotator.rotate_key(reason=str(e))
                time.sleep(1.5)

    raise RuntimeError(f"Failed to select Ayah with Groq LLM: {last_error}")
