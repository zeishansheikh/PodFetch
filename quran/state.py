"""State management module for the automated Quran ayah reel builder.
Tracks playlist progression (next_index), used ayahs, used background videos,
and build history in state.json according to Contract Section 5.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from logger import get_logger

logger = get_logger("quran_state")

DEFAULT_STATE_PATH = Path("quran/state.json")
ROOT_STATE_PATH = Path("state.json")


@dataclass
class ReelHistoryEntry:
    """Record of a successfully generated Quran reel."""

    date: str
    surah_number: int
    ayah_number: int
    surah_name_english: str
    surah_name_arabic: str
    reel_path: str
    duration_seconds: float
    drive_file_id: Optional[str] = None
    drive_link: Optional[str] = None
    playlist_video_id: Optional[str] = None
    playlist_index: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class QuranState:
    """Persistent state format specified in Contract Section 5."""

    playlist_url: str = ""
    next_index: int = 1
    used_ayahs: List[str] = field(default_factory=list)
    used_background_drive_ids: List[str] = field(default_factory=list)
    used_background_pin_ids: List[str] = field(default_factory=list)
    rolling_buffer: List[Dict[str, Any]] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StateManager:
    """Handles thread-safe reading, updating, and saving of Quran builder state."""

    def __init__(self, state_file: Optional[Path] = None) -> None:
        self.state_file = state_file or DEFAULT_STATE_PATH
        self.state = self.load()

    def load(self) -> QuranState:
        """Load state from state.json or initialize defaults."""
        target = self.state_file
        # Check fallback root state.json only when using default state path
        if self.state_file == DEFAULT_STATE_PATH and not target.exists() and ROOT_STATE_PATH.exists():
            target = ROOT_STATE_PATH

        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                return QuranState(
                    playlist_url=data.get("playlist_url", ""),
                    next_index=int(data.get("next_index", 1)),
                    used_ayahs=list(data.get("used_ayahs", [])),
                    used_background_drive_ids=list(data.get("used_background_drive_ids", [])),
                    used_background_pin_ids=list(data.get("used_background_pin_ids", [])),
                    rolling_buffer=list(data.get("rolling_buffer", [])),
                    history=list(data.get("history", [])),
                    last_updated=data.get("last_updated", datetime.now(timezone.utc).isoformat()),
                )
            except Exception as e:
                logger.warning(f"Failed to parse {target}, creating fresh state: {e}")

        fresh = QuranState()
        return fresh

    def save(self) -> None:
        """Persist state back to state.json."""
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self.state)
        content = json.dumps(data, indent=2, ensure_ascii=False)
        self.state_file.write_text(content, encoding="utf-8")
        # Also mirror to root state.json for easy inspection when using default path
        if self.state_file == DEFAULT_STATE_PATH:
            try:
                ROOT_STATE_PATH.write_text(content, encoding="utf-8")
            except Exception:
                pass

    def is_ayah_used(self, surah: int, ayah: int) -> bool:
        """Check if surah:ayah has already been used in any past reel."""
        key = f"{surah}:{ayah}"
        return key in self.state.used_ayahs

    def mark_ayah_used(self, surah: int, ayah: int) -> None:
        """Mark surah:ayah as used in state."""
        key = f"{surah}:{ayah}"
        if key not in self.state.used_ayahs:
            self.state.used_ayahs.append(key)
            self.save()

    def is_background_used(self, pin_id: Optional[str] = None, drive_id: Optional[str] = None) -> bool:
        """Check if background pin or Drive ID was previously used."""
        if drive_id and drive_id in self.state.used_background_drive_ids:
            return True
        if pin_id and pin_id in self.state.used_background_pin_ids:
            return True
        return False

    def mark_background_used(self, pin_id: Optional[str] = None, drive_id: Optional[str] = None) -> None:
        """Record used background pin or Drive ID."""
        if pin_id and pin_id not in self.state.used_background_pin_ids:
            self.state.used_background_pin_ids.append(pin_id)
        if drive_id and drive_id not in self.state.used_background_drive_ids:
            self.state.used_background_drive_ids.append(drive_id)
        self.save()

    def advance_index(self) -> int:
        """Advance playlist index by 1 in strict sequence."""
        self.state.next_index += 1
        self.save()
        return self.state.next_index

    def add_history(self, entry: ReelHistoryEntry) -> None:
        """Append reel generation record to history."""
        self.state.history.append(asdict(entry))
        self.mark_ayah_used(entry.surah_number, entry.ayah_number)
        if entry.drive_file_id:
            self.mark_background_used(drive_id=entry.drive_file_id)
        self.save()
