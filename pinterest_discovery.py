"""
Pinterest discovery module for PodFetch.
Discovers public video Pins using configured keywords, collects canonical URLs,
extracts metadata, filters out static images, tracks discovering keywords,
deduplicates results across multiple queries, and safely continues on search errors.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from config import AppConfig
from database import Database, VideoStatus
from filters import VideoCandidate
from logger import get_logger

logger = get_logger("pinterest_discovery")


@dataclass
class PinterestPinMetadata:
    """Metadata extracted for a discovered Pinterest Pin."""

    pin_id: str
    canonical_url: str
    title: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_video: bool = False
    duration_seconds: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    discovered_keywords: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_vertical(self) -> Optional[bool]:
        if self.width and self.height:
            return self.height > self.width
        return None

    def to_video_candidate(self, keyword: str = "") -> VideoCandidate:
        """Convert metadata into a VideoCandidate object."""
        kw = keyword or (self.discovered_keywords[0] if self.discovered_keywords else "")
        return VideoCandidate(
            youtube_video_id=self.pin_id,
            channel_id=f"pinterest_{kw.replace(' ', '_')}" if kw else "pinterest",
            channel_name="Pinterest",
            title=self.title,
            youtube_url=self.canonical_url,
            published_at=None,
            duration_seconds=self.duration_seconds,
            is_short=False,
            is_live=False,
            platform="pinterest",
            source_id=self.pin_id,
            canonical_url=self.canonical_url,
            search_keyword=kw,
            width=self.width,
            height=self.height,
            thumbnail_url=self.thumbnail_url,
            description=self.description,
            is_image=not self.is_video,
        )


def parse_pin_from_dict(pin_data: Dict[str, Any], keyword: str = "") -> Optional[PinterestPinMetadata]:
    """Parse raw Pin dictionary from official API or Resource endpoint into PinterestPinMetadata."""
    if not isinstance(pin_data, dict):
        return None

    pin_id = str(pin_data.get("id") or "").strip()
    if not pin_id:
        return None

    # Canonical URL
    canonical_url = f"https://www.pinterest.com/pin/{pin_id}/"

    # Title extraction
    title = (
        pin_data.get("title")
        or pin_data.get("grid_title")
        or pin_data.get("name")
        or ""
    ).strip()

    # Description extraction
    description = (
        pin_data.get("description")
        or pin_data.get("seo_description")
        or ""
    ).strip() or None

    # Thumbnail extraction
    thumbnail_url = None
    images = pin_data.get("images")
    if isinstance(images, dict):
        for size_key in ("orig", "736x", "474x", "236x"):
            img = images.get(size_key)
            if isinstance(img, dict) and img.get("url"):
                thumbnail_url = img["url"]
                break
    elif pin_data.get("media", {}).get("images"):
        # Official API v5 format
        media_imgs = pin_data.get("media", {}).get("images", {})
        if isinstance(media_imgs, dict):
            for sz in ("1200x", "600x", "150x150"):
                if sz in media_imgs and media_imgs[sz].get("url"):
                    thumbnail_url = media_imgs[sz]["url"]
                    break

    # Video detection and stream metadata
    is_video = False
    duration_seconds: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

    # Check videos dictionary
    videos = pin_data.get("videos")
    if isinstance(videos, dict) and videos.get("video_list"):
        is_video = True
        video_list = videos.get("video_list", {})
        if isinstance(video_list, dict):
            max_pixels = 0
            best_info = None
            for fmt_info in video_list.values():
                if isinstance(fmt_info, dict):
                    w = fmt_info.get("width") or 0
                    h = fmt_info.get("height") or 0
                    dur = fmt_info.get("duration")
                    if duration_seconds is None and dur is not None:
                        duration_seconds = int(dur / 1000) if dur > 1000 else int(dur)
                    if (w * h) > max_pixels:
                        max_pixels = w * h
                        best_info = fmt_info

            if best_info:
                width = best_info.get("width")
                height = best_info.get("height")
                dur = best_info.get("duration")
                if dur is not None:
                    duration_seconds = int(dur / 1000) if dur > 1000 else int(dur)

    # Check story_pin_data (Idea Pins format)
    if not is_video and pin_data.get("story_pin_data"):
        story_data = pin_data["story_pin_data"]
        if isinstance(story_data, dict):
            pages = story_data.get("pages", [])
            for page in pages:
                if isinstance(page, dict):
                    blocks = page.get("blocks", [])
                    for block in blocks:
                        if isinstance(block, dict) and block.get("video"):
                            is_video = True
                            vid_info = block.get("video", {})
                            vid_list = vid_info.get("video_list", {})
                            for fmt in vid_list.values():
                                if isinstance(fmt, dict):
                                    width = fmt.get("width")
                                    height = fmt.get("height")
                                    if fmt.get("duration"):
                                        dur = fmt.get("duration")
                                        duration_seconds = int(dur / 1000) if dur > 1000 else int(dur)
                                    break
                            break

    # Official API v5 video detection
    media_data = pin_data.get("media")
    if isinstance(media_data, dict):
        media_type = media_data.get("media_type")
        if media_type in ("video", "video_list"):
            is_video = True
            if media_data.get("duration"):
                dur = media_data["duration"]
                duration_seconds = int(dur / 1000) if dur > 1000 else int(dur)
            if media_data.get("width"):
                width = int(media_data["width"])
            if media_data.get("height"):
                height = int(media_data["height"])

    if bool(pin_data.get("is_video")):
        is_video = True

    # Fallback title if empty
    if not title:
        if description:
            title = description[:60]
        elif keyword:
            title = f"{keyword.title()} Pin {pin_id}"
        else:
            title = f"Pinterest Video {pin_id}"

    return PinterestPinMetadata(
        pin_id=pin_id,
        canonical_url=canonical_url,
        title=title,
        description=description,
        thumbnail_url=thumbnail_url,
        is_video=is_video,
        duration_seconds=duration_seconds,
        width=width,
        height=height,
        discovered_keywords=[keyword] if keyword else [],
        raw_data=pin_data,
    )


class PinterestDiscoverer:
    """Discovers matching video Pins across configured Pinterest keywords."""

    def __init__(self, config: AppConfig, db: Database) -> None:
        self.config = config
        self.db = db

    def discover_pins_by_keyword(self, keyword: str, limit: int = 15) -> List[PinterestPinMetadata]:
        """Discover pins matching a specific keyword, limited to requested count."""
        pins = self.search_keyword(keyword)
        return pins[:limit]

    def _query_official_api(self, keyword: str, limit: int = 25) -> List[PinterestPinMetadata]:
        """Query official Pinterest API v5 if access token is configured."""
        if not self.config.pinterest_access_token:
            return []

        url = (
            f"https://api.pinterest.com/v5/search/partner/pins?"
            f"term={urllib.parse.quote(keyword)}&country_code=US&limit={limit}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.config.pinterest_access_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            logger.info(f"Querying official Pinterest API for '{keyword}'...")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                pins: List[PinterestPinMetadata] = []
                for item in items:
                    parsed = parse_pin_from_dict(item, keyword=keyword)
                    if parsed:
                        pins.append(parsed)
                return pins
        except Exception as e:
            logger.warning(f"Official Pinterest API query failed for '{keyword}': {e}")
            return []

    def _query_resource_api(self, keyword: str, limit: int = 25) -> List[PinterestPinMetadata]:
        """Query Pinterest internal BaseSearchResource endpoint with permitted headers."""
        data_payload = {
            "options": {
                "query": keyword,
                "scope": "pins",
                "page_size": limit,
            },
            "context": {},
        }
        url = (
            f"https://www.pinterest.com/resource/BaseSearchResource/get/?"
            f"data={urllib.parse.quote(json.dumps(data_payload))}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "X-Pinterest-AppState": "active",
            "X-Pinterest-PWS-Handler": "www/[username].js",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        if self.config.pinterest_session_cookie:
            headers["Cookie"] = self.config.pinterest_session_cookie

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("resource_response", {}).get("data", {}).get("results", [])
                pins: List[PinterestPinMetadata] = []
                for item in results:
                    parsed = parse_pin_from_dict(item, keyword=keyword)
                    if parsed:
                        pins.append(parsed)
                if pins:
                    return pins
        except Exception as e:
            logger.warning(f"Pinterest Resource pin search query failed for '{keyword}': {e}")

        # If direct unauthenticated pin search returned 0 results, query matching public boards
        board_pins = self._query_board_feed_pins(keyword)
        if board_pins:
            return board_pins

        return []

    def _query_board_feed_pins(
        self, keyword: str, max_boards: int = 3, pins_per_board: int = 20
    ) -> List[PinterestPinMetadata]:
        """Discover video Pins from public boards matching the keyword.

        When unauthenticated direct pin search returns empty results, queries public boards
        matching the search keyword and extracts video Pins from those boards.
        """
        board_data = {
            "options": {
                "query": keyword,
                "scope": "boards",
                "page_size": max_boards,
            },
            "context": {},
        }
        url = (
            f"https://www.pinterest.com/resource/BaseSearchResource/get/?"
            f"data={urllib.parse.quote(json.dumps(board_data))}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "X-Pinterest-AppState": "active",
            "X-Pinterest-PWS-Handler": "www/[username].js",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        if self.config.pinterest_session_cookie:
            headers["Cookie"] = self.config.pinterest_session_cookie

        discovered_pins: List[PinterestPinMetadata] = []
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                boards = data.get("resource_response", {}).get("data", {}).get("results", [])

            for b in boards[:max_boards]:
                board_id = b.get("id")
                if not board_id:
                    continue

                feed_data = {
                    "options": {
                        "board_id": str(board_id),
                        "page_size": pins_per_board,
                    },
                    "context": {},
                }
                feed_url = (
                    f"https://www.pinterest.com/resource/BoardFeedResource/get/?"
                    f"data={urllib.parse.quote(json.dumps(feed_data))}"
                )
                try:
                    feed_req = urllib.request.Request(feed_url, headers=headers)
                    with urllib.request.urlopen(feed_req, timeout=10) as f_resp:
                        f_data = json.loads(f_resp.read().decode("utf-8"))
                        board_pins = f_data.get("resource_response", {}).get("data", []) or []
                        for item in board_pins:
                            if isinstance(item, dict):
                                parsed = parse_pin_from_dict(item, keyword=keyword)
                                if parsed:
                                    discovered_pins.append(parsed)
                except Exception as fe:
                    logger.debug(f"Failed fetching board {board_id} feed: {fe}")

        except Exception as be:
            logger.debug(f"Board search fallback failed for '{keyword}': {be}")

        return discovered_pins

    def fetch_pin_details(self, pin_id: str) -> Optional[PinterestPinMetadata]:
        """Fetch full PinResource metadata for a specific Pin ID to verify video media."""
        options = {
            "field_set_key": "unauth_react_main_pin",
            "id": str(pin_id),
        }
        url = (
            f"https://www.pinterest.com/resource/PinResource/get/?"
            f"data={urllib.parse.quote(json.dumps({'options': options}))}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "X-Pinterest-PWS-Handler": "www/[username].js",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                pin_data = data.get("resource_response", {}).get("data", {})
                if pin_data and isinstance(pin_data, dict):
                    return parse_pin_from_dict(pin_data)
        except Exception as e:
            logger.debug(f"Failed to fetch PinResource details for {pin_id}: {e}")
        return None

    def search_keyword(self, keyword: str) -> List[PinterestPinMetadata]:
        """Search Pinterest for matching Pins using permitted methods."""
        cleaned_kw = keyword.strip()
        # 0. Check if keyword is a direct Pin URL or Pin ID
        pin_id_match = re.search(r"/pin/(\d+)", cleaned_kw)
        if not pin_id_match and re.match(r"^\d{10,25}$", cleaned_kw):
            direct_id = cleaned_kw
        elif pin_id_match:
            direct_id = pin_id_match.group(1)
        else:
            direct_id = None

        if direct_id:
            logger.info(f"Targeting direct Pinterest Pin ID: {direct_id}")
            direct_pin = self.fetch_pin_details(direct_id)
            if direct_pin:
                return [direct_pin]

        # 1. Try official API first if token is available
        if self.config.pinterest_access_token:
            api_results = self._query_official_api(cleaned_kw)
            if api_results:
                return api_results

        # 2. Try permitted Resource API
        resource_results = self._query_resource_api(cleaned_kw)
        if resource_results:
            return resource_results

        # 3. If no results returned or automated access is restricted
        logger.warning(
            f"Pinterest search for '{keyword}' returned 0 results or is restricted. "
            "(Automated Pinterest search requires an authorized session or official "
            "PINTEREST_ACCESS_TOKEN. Continuing to next keyword...)"
        )
        return []

    def discover_all_keywords(
        self, keywords: Optional[List[str]] = None
    ) -> Tuple[List[VideoCandidate], int, int, List[str]]:
        """Search all configured Pinterest keywords, filter video media, and deduplicate.

        Uses concurrent worker threads to query multiple keywords in parallel, accelerating
        discovery by up to 10x, and stops searching once an adequate candidate pool is reached.

        Returns:
            Tuple of:
            - List of eligible VideoCandidate objects
            - Total candidates examined
            - Total skipped (duplicates + static images)
            - List of search error messages / warnings
        """
        import concurrent.futures

        target_keywords = keywords or self.config.pinterest_keywords
        logger.info(f"Checking {len(target_keywords)} configured Pinterest keyword(s)...")

        seen_pins: Dict[str, VideoCandidate] = {}
        total_examined = 0
        total_skipped = 0
        search_errors: List[str] = []

        max_workers = min(len(target_keywords), getattr(self.config, "discovery_max_workers", 6))
        candidate_pool = getattr(self.config, "discovery_candidate_pool", 30)

        def _process_pins_for_keyword(kw: str, pins: List[PinterestPinMetadata]) -> None:
            nonlocal total_examined, total_skipped
            total_examined += len(pins)
            for pin in pins:
                # Exclude static images
                if not pin.is_video:
                    total_skipped += 1
                    logger.debug(f"Skipped static image Pin {pin.pin_id} for keyword '{kw}'")
                    continue

                # Deduplication across keywords
                if pin.pin_id in seen_pins:
                    total_skipped += 1
                    existing_cand = seen_pins[pin.pin_id]
                    # Preserve additional discovery keyword
                    if existing_cand.search_keyword and kw not in existing_cand.search_keyword:
                        existing_cand.search_keyword = f"{existing_cand.search_keyword}, {kw}"
                    logger.debug(
                        f"Duplicate Pin {pin.pin_id} discovered again under keyword '{kw}'; preserved keyword"
                    )
                    continue

                # Create VideoCandidate for video Pin
                candidate = VideoCandidate(
                    youtube_video_id=pin.pin_id,
                    channel_id=f"pinterest_{kw.replace(' ', '_')}",
                    channel_name="Pinterest",
                    title=pin.title,
                    youtube_url=pin.canonical_url,
                    published_at=None,
                    duration_seconds=pin.duration_seconds,
                    is_short=False,
                    is_live=False,
                    platform="pinterest",
                    source_id=pin.pin_id,
                    canonical_url=pin.canonical_url,
                    search_keyword=kw,
                    width=pin.width,
                    height=pin.height,
                    thumbnail_url=pin.thumbnail_url,
                    description=pin.description,
                    is_image=False,
                )
                seen_pins[pin.pin_id] = candidate

        if max_workers <= 1 or len(target_keywords) <= 1:
            for kw in target_keywords:
                try:
                    pins = self.search_keyword(kw)
                    _process_pins_for_keyword(kw, pins)
                    if candidate_pool > 0 and len(seen_pins) >= candidate_pool:
                        logger.info(
                            f"Target candidate pool reached ({len(seen_pins)} video pins). "
                            "Stopping additional keyword searches."
                        )
                        break
                except Exception as e:
                    err_msg = f"Failed searching Pinterest keyword '{kw}': {e}"
                    logger.error(err_msg)
                    search_errors.append(err_msg)
                    continue
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_kw = {
                    executor.submit(self.search_keyword, kw): kw
                    for kw in target_keywords
                }
                for future in concurrent.futures.as_completed(future_to_kw):
                    kw = future_to_kw[future]
                    try:
                        pins = future.result()
                        _process_pins_for_keyword(kw, pins)

                        if candidate_pool > 0 and len(seen_pins) >= candidate_pool:
                            logger.info(
                                f"Target candidate pool reached ({len(seen_pins)} video pins). "
                                "Cancelling pending keyword searches for faster execution."
                            )
                            for pending_f in future_to_kw:
                                pending_f.cancel()
                            break

                    except Exception as e:
                        err_msg = f"Failed searching Pinterest keyword '{kw}': {e}"
                        logger.error(err_msg)
                        search_errors.append(err_msg)
                        continue

        eligible_candidates = list(seen_pins.values())
        logger.info(
            f"Pinterest discovery complete: {len(eligible_candidates)} unique video candidate(s) found, "
            f"{total_skipped} skipped (static images/duplicates)."
        )
        return eligible_candidates, total_examined, total_skipped, search_errors
