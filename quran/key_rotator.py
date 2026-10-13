"""Groq API Key rotation module.
Provides seamless fallback and rotation through GROQ_API_KEY and numbered
fallbacks (GROQ_API_KEY_2/3/4) upon rate limits or authentication errors.
"""

from __future__ import annotations

import os
import threading
from typing import List, Optional

from logger import get_logger

logger = get_logger("quran_key_rotator")


class GroqKeyRotator:
    """Manages pool of Groq API keys with rotation on failure."""

    _instance: Optional[GroqKeyRotator] = None

    def __init__(self, keys: Optional[List[str]] = None) -> None:
        self._lock = threading.Lock()
        self._keys: List[str] = list(keys) if keys is not None else []
        self._current_index = 0
        if keys is None:
            self._load_keys()

    def _load_keys(self) -> None:
        """Collect all configured Groq keys from environment variables."""
        candidate_names = [
            "GROQ_API_KEY",
            "GROQ_API_KEY_2",
            "GROQ_API_KEY_3",
            "GROQ_API_KEY_4",
            "AI_API_KEY_1",
            "AI_API_KEY_2",
            "AI_API_KEY_3",
            "AI_API_KEY_4",
        ]
        seen = set()
        for name in candidate_names:
            val = os.getenv(name, "").strip()
            if val and val.startswith("gsk_") and val not in seen:
                self._keys.append(val)
                seen.add(val)

        logger.info(f"Initialized Groq key rotator with {len(self._keys)} active key(s).")

    @property
    def has_keys(self) -> bool:
        return len(self._keys) > 0

    def get_current_key(self) -> str:
        """Retrieve the currently active Groq API key."""
        with self._lock:
            if not self._keys:
                # Fallback to direct env fetch
                direct = os.getenv("GROQ_API_KEY", "").strip()
                if direct:
                    return direct
                raise ValueError("No GROQ_API_KEY found in environment or .env file.")
            return self._keys[self._current_index]

    def rotate_key(self, reason: str = "") -> str:
        """Switch to the next available API key in the pool."""
        with self._lock:
            if len(self._keys) <= 1:
                logger.warning(f"Groq API key error ({reason}), but only 1 key is configured.")
                return self._keys[0] if self._keys else ""

            prev_idx = self._current_index
            self._current_index = (self._current_index + 1) % len(self._keys)
            masked_prev = f"{self._keys[prev_idx][:8]}...{self._keys[prev_idx][-4:]}"
            masked_new = f"{self._keys[self._current_index][:8]}...{self._keys[self._current_index][-4:]}"
            logger.warning(
                f"Rotating Groq API key due to '{reason}': switched from {masked_prev} to {masked_new}."
            )
            return self._keys[self._current_index]


def get_key_rotator() -> GroqKeyRotator:
    """Singleton getter for Groq key rotator."""
    if GroqKeyRotator._instance is None:
        GroqKeyRotator._instance = GroqKeyRotator()
    return GroqKeyRotator._instance
