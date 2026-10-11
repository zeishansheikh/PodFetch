"""
Audio manifest manager for PodFetch Instagram Trending Audio.
Provides atomic persistence and structured query interface for downstream
video-processing agents to discover newly available and authorized audio files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from logger import get_logger

logger = get_logger("audio_manifest")


class AudioManifestManager:
    """Manages the audio_manifest.json file for downstream consumption."""

    def __init__(self, manifest_path: Path | str = "audio_manifest.json") -> None:
        self.manifest_path = Path(manifest_path)

    def load_manifest(self) -> Dict[str, Any]:
        """Load manifest from disk or return default structure if nonexistent."""
        if not self.manifest_path.exists():
            return {
                "version": "1.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_tracks": 0,
                "tracks": [],
            }

        try:
            content = self.manifest_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict) and "tracks" in data:
                return data
        except Exception as e:
            logger.warning(f"Error reading audio manifest {self.manifest_path}: {e}. Initializing fresh manifest.")

        return {
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_tracks": 0,
            "tracks": [],
        }

    def get_track(self, audio_id: str) -> Optional[Dict[str, Any]]:
        """Find a track in the manifest by its audio_id."""
        manifest = self.load_manifest()
        for track in manifest.get("tracks", []):
            if track.get("audio_id") == audio_id:
                return track
        return None

    def get_available_tracks(self) -> List[Dict[str, Any]]:
        """Return all tracks that are successfully uploaded or downloaded."""
        manifest = self.load_manifest()
        return [
            t
            for t in manifest.get("tracks", [])
            if t.get("status") in ("UPLOADED", "DOWNLOADED")
        ]

    def add_or_update_track(
        self,
        audio_id: str,
        title: str,
        artist: str,
        source_url: str,
        discovered_at: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        popularity: Optional[Dict[str, Any]] = None,
        is_authorized: bool = True,
        audio_file: Optional[str] = None,
        local_path: Optional[str] = None,
        drive_file_id: Optional[str] = None,
        drive_path: Optional[str] = None,
        metadata_drive_file_id: Optional[str] = None,
        status: str = "UPLOADED",
        uploaded_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add or update a track entry and atomically save the manifest."""
        manifest = self.load_manifest()
        tracks: List[Dict[str, Any]] = manifest.get("tracks", [])

        now_iso = datetime.now(timezone.utc).isoformat()
        disc_date = discovered_at or now_iso

        track_entry: Optional[Dict[str, Any]] = None
        for t in tracks:
            if t.get("audio_id") == audio_id:
                track_entry = t
                break

        if track_entry is None:
            track_entry = {
                "audio_id": audio_id,
                "title": title,
                "artist": artist,
                "source_url": source_url,
                "discovered_at": disc_date,
                "created_at": now_iso,
            }
            tracks.append(track_entry)

        # Update properties
        track_entry["title"] = title
        track_entry["artist"] = artist
        track_entry["source_url"] = source_url
        if duration_seconds is not None:
            track_entry["duration_seconds"] = duration_seconds
        if popularity:
            track_entry["popularity"] = popularity
        track_entry["is_authorized"] = is_authorized

        if audio_file:
            track_entry["audio_file"] = audio_file
        if local_path:
            track_entry["local_path"] = str(local_path)
        if drive_file_id:
            track_entry["drive_file_id"] = drive_file_id
        if drive_path:
            track_entry["drive_path"] = drive_path
        if metadata_drive_file_id:
            track_entry["metadata_drive_file_id"] = metadata_drive_file_id

        track_entry["status"] = status
        if uploaded_at:
            track_entry["uploaded_at"] = uploaded_at
        elif status == "UPLOADED" and "uploaded_at" not in track_entry:
            track_entry["uploaded_at"] = now_iso

        track_entry["last_updated"] = now_iso

        manifest["tracks"] = tracks
        manifest["total_tracks"] = len(tracks)
        manifest["last_updated"] = now_iso

        self._save_manifest(manifest)
        return track_entry

    def _save_manifest(self, manifest: Dict[str, Any]) -> None:
        """Write manifest atomically to disk to prevent corruption."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.manifest_path.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.manifest_path)
            logger.debug(f"Saved audio manifest to {self.manifest_path} (total: {manifest['total_tracks']})")
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            logger.error(f"Failed to atomically write audio manifest: {e}", exc_info=True)
            raise
