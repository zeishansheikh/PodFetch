"""End-to-end processing pipeline for the Nature Cinematic Reel Maker."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.request

from config import AppConfig
from database import Database
from drive_uploader import GoogleDriveUploader
from filters import VideoCandidate
from logger import get_logger
from nature.models import (
    CompositionMode,
    JobStage,
    NatureCandidate,
    NatureProfile,
    NatureQualityScore,
    NatureReel,
    NatureTemplateConfig,
    ReelStatus,
    TEMPLATE_MINIMAL_WHITE_SERIF,
    TEMPLATE_THOUGHT_REEL,
)
from nature.profile import ProfileManager
from nature.quality_filter import NatureQualityFilter
from nature.template import NatureTemplateRenderer
from nature.thoughts_generator import NatureThoughtsGenerator
from pinterest_discovery import PinterestDiscoverer
from pinterest_downloader import PinterestDownloader

logger = get_logger("nature_pipeline")


class NaturePipeline:
    """Orchestrates 15-stage workflow from keyword rotation to discovery,

    quality scoring, download, AI thought generation, template rendering,
    and Google Drive backup.
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        db: Optional[Database] = None,
        base_dir: Optional[Path] = None,
    ):
        self.config = config or AppConfig()
        db_path = getattr(self.config, "database_path", Path("downloads.db"))
        self.db = db or Database(db_path)
        dl_dir = getattr(self.config, "download_dir", Path("downloads"))
        self.base_dir = base_dir or Path(dl_dir) / "nature"
        self.originals_dir = self.base_dir / "originals"
        self.reels_dir = self.base_dir / "reels"
        self.thumbnails_dir = self.base_dir / "thumbnails"

        self.originals_dir.mkdir(parents=True, exist_ok=True)
        self.reels_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)

        self.profile_manager = ProfileManager(self._load_or_create_profile())
        self.quality_filter = NatureQualityFilter(self.profile_manager.profile)
        self.template_renderer = NatureTemplateRenderer(NatureTemplateConfig())
        self.thoughts_generator = NatureThoughtsGenerator()

        # Job state tracking
        self._stop_requested = False
        self._current_job_id: Optional[str] = None
        self._lock = threading.Lock()

    def _load_or_create_profile(self) -> NatureProfile:
        """Load stored profile from SQLite or create default."""
        stored = self.db.get_nature_profile("Nature Cinematic Reels")
        if stored:
            return NatureProfile(
                name=stored["name"],
                categories=stored["categories"],
                custom_keywords=stored["custom_keywords"],
                excluded_terms=stored["excluded_terms"],
                search_limit=stored["search_limit"],
                daily_processing_limit=stored["daily_processing_limit"],
                min_quality_score=stored["min_quality_score"],
                is_active=stored["is_active"],
            )
        default_prof = NatureProfile()
        self.db.save_nature_profile(default_prof.to_dict())
        return default_prof

    def reload_profile(self) -> NatureProfile:
        """Refresh profile from database."""
        prof = self._load_or_create_profile()
        self.profile_manager = ProfileManager(prof)
        self.quality_filter = NatureQualityFilter(prof)
        return prof

    def stop(self) -> None:
        """Signal active pipeline job to stop."""
        with self._lock:
            self._stop_requested = True
            logger.info("Pipeline stop signal sent.")

    def run_pipeline(
        self,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        mood: Optional[str] = None,
        season: Optional[str] = None,
        recency_preference: Optional[str] = None,
        strict_recency: Optional[bool] = None,
        preferred_orientation: Optional[str] = None,
        min_quality_score: Optional[float] = None,
        search_limit: Optional[int] = None,
        excluded_terms: Optional[List[str]] = None,
        max_reels: int = 1,
        composition_mode: str = CompositionMode.CROP.value,
        force_mock_if_empty: bool = False,
        template_name: Optional[str] = None,
        custom_thought: Optional[str] = None,
        target_duration: Optional[float] = None,
        font_size: Optional[int] = None,
        line_spacing: Optional[int] = None,
        music_path: Optional[str] = None,
        music_volume: Optional[float] = None,
        source_audio_volume: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute the automated Nature Reel pipeline."""
        with self._lock:
            self._stop_requested = False
            job_id = f"job_nature_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            self._current_job_id = job_id

        logger.info(f"Starting Nature Pipeline [{job_id}]")
        self._update_job_status(job_id, JobStage.DISCOVERING, progress=5, rendered_reels=0)

        # 1. Effective Settings & Smart Query Generation
        eff_mood = (mood or self.profile_manager.profile.search_mood or "cinematic").strip()
        eff_season = (season or self.profile_manager.profile.season or "any").strip()
        eff_orientation = (preferred_orientation or self.profile_manager.profile.preferred_orientation or "vertical_9_16").strip()
        eff_recency = (recency_preference or self.profile_manager.profile.recency_preference or "any").strip()
        eff_strict_recency = strict_recency if strict_recency is not None else self.profile_manager.profile.strict_recency
        eff_threshold = min_quality_score if min_quality_score is not None else self.profile_manager.profile.min_quality_score
        eff_limit = search_limit or self.profile_manager.profile.search_limit or 15

        if excluded_terms:
            combined_ex = list(dict.fromkeys(self.profile_manager.profile.excluded_terms + excluded_terms))
            self.profile_manager.profile.excluded_terms = combined_ex

        raw_cat = category or (self.profile_manager.profile.categories[0] if self.profile_manager.profile.categories else "autumn_forest")
        resolved_category, base_keyword, search_query = self.profile_manager.generate_search_query(
            category_id=raw_cat,
            keyword=keyword,
            mood=eff_mood,
            season=eff_season,
            orientation=eff_orientation,
            randomize=True if not keyword else False,
        )

        # Template configuration
        chosen_template = template_name or TEMPLATE_MINIMAL_WHITE_SERIF
        template_cfg = NatureTemplateConfig.from_preset(chosen_template)
        template_cfg.composition_mode = composition_mode
        if font_size:
            template_cfg.font_size = font_size
        if line_spacing is not None:
            template_cfg.line_spacing = line_spacing
        if target_duration:
            template_cfg.target_duration = target_duration
        if music_path:
            template_cfg.music_path = music_path
        if music_volume is not None:
            template_cfg.music_volume = music_volume
        if source_audio_volume is not None:
            template_cfg.source_audio_volume = source_audio_volume

        eff_duration = target_duration or template_cfg.target_duration

        self._update_job_status(
            job_id,
            JobStage.DISCOVERING,
            progress=15,
            current_category=resolved_category,
            current_keyword=base_keyword,
        )

        # 2. Pinterest Discovery using Smart Query
        discovered_candidates = self._discover_candidates(
            category=resolved_category,
            keyword=base_keyword,
            search_query=search_query,
            limit=eff_limit,
        )

        if not discovered_candidates and force_mock_if_empty:
            logger.warning("No online Pinterest candidates discovered; checking local cache.")

        self._update_job_status(
            job_id,
            JobStage.FILTERING,
            progress=30,
            total_candidates=len(discovered_candidates),
        )

        already_processed = self.db.get_all_nature_candidate_ids()

        # 3. Pre-Download Ranking and Multi-factor Gating
        for cand in discovered_candidates:
            if cand.source_id in already_processed:
                cand.eligibility_status = "REJECTED"
                cand.rejection_reason = "Duplicate candidate already processed"
                self.db.save_nature_candidate(cand.to_dict())
                continue

            pre_score, pre_eligible, pre_reasons = self.quality_filter.evaluate_pre_download(
                candidate=cand,
                recency_preference=eff_recency,
                strict_recency=eff_strict_recency,
                preferred_orientation=eff_orientation,
                min_quality_score=eff_threshold,
            )
            cand.pre_score = pre_score
            if not pre_eligible:
                cand.eligibility_status = "REJECTED"
                cand.rejection_reason = "; ".join(pre_reasons)
            else:
                cand.eligibility_status = "ELIGIBLE"
                cand.rejection_reason = None
            self.db.save_nature_candidate(cand.to_dict())

        # Sort candidates descending: eligible first, then highest pre_score
        discovered_candidates.sort(
            key=lambda c: (1 if c.eligibility_status != "REJECTED" else 0, c.pre_score or 0.0),
            reverse=True,
        )

        # Record keyword search statistics in history
        eligible_count = sum(1 for c in discovered_candidates if c.eligibility_status != "REJECTED")
        self.db.record_nature_keyword_search(
            category=resolved_category,
            keyword=base_keyword,
            query=search_query,
            mood=eff_mood,
            season=eff_season,
            candidates_found=len(discovered_candidates),
            videos_found=len(discovered_candidates),
            eligible_found=eligible_count,
        )
        self.profile_manager.record_keyword_result(base_keyword, eligible_count)

        rendered_count = 0

        for idx, candidate in enumerate(discovered_candidates):
            if self._stop_requested:
                logger.info("Pipeline stopped by user.")
                self._update_job_status(job_id, JobStage.PAUSED, progress=round((idx / max(len(discovered_candidates), 1)) * 100))
                break

            if rendered_count >= max_reels:
                break

            # Skip candidates rejected at pre-download stage
            if candidate.eligibility_status == "REJECTED":
                logger.info(f"Skipping pre-download rejected candidate {candidate.source_id}: {candidate.rejection_reason}")
                continue

            # 4. Download Media File
            self._update_job_status(job_id, JobStage.DOWNLOADING, progress=45)
            cat_dir = self.originals_dir / resolved_category
            cat_dir.mkdir(parents=True, exist_ok=True)
            local_filename = f"{candidate.source_id}.mp4"
            target_download_path = cat_dir / local_filename

            download_ok = self._download_candidate_media(candidate, target_download_path)
            if not download_ok:
                candidate.eligibility_status = "REJECTED"
                candidate.rejection_reason = "Media download failed or source has no playable stream"
                self.db.save_nature_candidate(candidate.to_dict())
                continue

            # 5. Deep Multi-factor Quality Inspection (Post-download)
            self._update_job_status(job_id, JobStage.VALIDATING, progress=60)
            score = self.quality_filter.evaluate_candidate(
                candidate=candidate,
                local_video_path=target_download_path,
                already_processed_ids=already_processed,
                recency_preference=eff_recency,
                strict_recency=eff_strict_recency,
                preferred_orientation=eff_orientation,
            )
            self.db.save_nature_candidate(candidate.to_dict())

            if not score.passed_gate:
                logger.info(f"Candidate {candidate.source_id} rejected after download inspection: {candidate.rejection_reason}")
                continue

            # 7. AI Poetic Thought & Caption Generation
            self._update_job_status(job_id, JobStage.GENERATING_THOUGHTS, progress=75)
            past_thoughts = self.db.get_recent_nature_thoughts(limit=50)
            thought = self.thoughts_generator.generate_thought_and_caption(
                category=category,
                keyword=keyword,
                past_thoughts=past_thoughts,
                creator_attribution=candidate.creator_attribution,
            )

            eff_thought_text = custom_thought.strip() if (custom_thought and custom_thought.strip()) else thought.thought_text

            # 8. Template Video Rendering
            self._update_job_status(job_id, JobStage.RENDERING, progress=85)
            reel_filename = f"{candidate.source_id}_nature_reel.mp4"
            rendered_reel_path = self.reels_dir / reel_filename
            thumb_path = self.thumbnails_dir / f"{candidate.source_id}.jpg"

            render_ok, render_err = self.template_renderer.render_reel(
                input_video_path=target_download_path,
                thought_text=eff_thought_text,
                output_reel_path=rendered_reel_path,
                target_duration=eff_duration,
                composition_mode=composition_mode,
                template_config=template_cfg,
            )

            if not render_ok:
                logger.error(f"Render failed for candidate {candidate.source_id}: {render_err}")
                candidate.eligibility_status = "REJECTED"
                candidate.rejection_reason = f"Render error: {render_err}"
                self.db.save_nature_candidate(candidate.to_dict())
                continue

            # Extract thumbnail
            self.template_renderer.generate_thumbnail(rendered_reel_path, thumb_path, timestamp=1.5)

            # 9. Google Drive Upload (Optional backup if configured)
            drive_file_id = None
            drive_link = None
            if getattr(self.config, "drive_upload_enabled", True):
                try:
                    self._update_job_status(job_id, JobStage.UPLOADING, progress=92)
                    drive_uploader = GoogleDriveUploader(self.config)
                    drive_file_id, drive_link = drive_uploader.upload_file(
                        file_path=rendered_reel_path,
                        platform=f"nature_{category}",
                        description=f"Nature Cinematic Reel: {eff_thought_text}",
                    )
                except Exception as e:
                    logger.warning(f"Google Drive upload skipped/failed: {e}")

            # 10. Persist Rendered Reel Asset to SQLite (Status = PENDING review)
            reel = NatureReel(
                source_id=candidate.source_id,
                candidate_url=candidate.canonical_url,
                category=category,
                keyword=keyword,
                original_video_path=str(target_download_path),
                rendered_reel_path=str(rendered_reel_path),
                thumbnail_path=str(thumb_path) if thumb_path.exists() else None,
                thought_text=eff_thought_text,
                caption=thought.caption,
                hashtags=thought.hashtags,
                title_hook=thought.title_hook,
                creator_attribution=candidate.creator_attribution,
                template_name=chosen_template,
                template_version="2.0.0",
                composition_mode=composition_mode,
                duration_seconds=eff_duration,
                width=1080,
                height=1920,
                fps=30,
                ai_model_name=thought.model_name if not custom_thought else "User-Edited",
                status=ReelStatus.PENDING.value,
                drive_file_id=drive_file_id,
                drive_link=drive_link,
                uploaded_at=datetime.now(timezone.utc).isoformat() if drive_file_id else None,
            )
            reel_id = self.db.save_nature_reel(reel.to_dict())
            reel.id = reel_id
            rendered_count += 1
            already_processed.add(candidate.source_id)

            logger.info(f"Nature Reel created successfully! Reel ID: {reel_id}, Path: {rendered_reel_path}")

        final_stage = JobStage.COMPLETED if rendered_count > 0 else (JobStage.PAUSED if self._stop_requested else JobStage.COMPLETED)
        self._update_job_status(
            job_id,
            final_stage,
            progress=100,
            rendered_reels=rendered_count,
            processed_candidates=len(discovered_candidates),
        )

        return {
            "job_id": job_id,
            "status": final_stage.value,
            "category": category,
            "keyword": keyword,
            "candidates_found": len(discovered_candidates),
            "rendered_reels": rendered_count,
        }

    def _discover_candidates(
        self,
        category: str,
        keyword: str,
        search_query: Optional[str] = None,
        limit: int = 15,
    ) -> List[NatureCandidate]:
        """Discover video pins using existing PinterestDiscovery module."""
        candidates: List[NatureCandidate] = []
        try:
            discoverer = PinterestDiscoverer(self.config, self.db)
            effective_query = search_query or (keyword if "video" in keyword.lower() else f"{keyword} video")

            # 1. Query board feed pins which contain direct high-speed video_list stream URLs
            board_queries = [effective_query]
            cat_singular = category.split("_")[0].rstrip("s")
            alt_query = f"{cat_singular} video"
            if alt_query.lower() not in [q.lower() for q in board_queries]:
                board_queries.append(alt_query)

            video_pins = []
            for bq in board_queries:
                board_pins = discoverer._query_board_feed_pins(bq, max_boards=3, pins_per_board=15)
                for p in board_pins:
                    if p.is_video and p.raw_data and (p.raw_data.get("videos") or {}).get("video_list"):
                        video_pins.append(p)
                if len(video_pins) >= 5:
                    break

            # 2. If not enough board video pins found, fall back to resource search API
            if not video_pins:
                pins = discoverer._query_resource_api(effective_query, limit=limit)
                if not pins and keyword and keyword.lower() != effective_query.lower():
                    # Fallback to base keyword
                    pins = discoverer._query_resource_api(keyword, limit=limit)
                if not pins:
                    # Fallback to streamlined category search
                    cat_clean = category.replace("_", " ")
                    pins = discoverer._query_resource_api(f"cinematic {cat_clean} video", limit=limit)

                for p in pins:
                    if p.is_video:
                        if p.raw_data and (p.raw_data.get("videos") or {}).get("video_list"):
                            video_pins.append(p)
                        else:
                            details = discoverer.fetch_pin_details(p.pin_id)
                            if details and details.raw_data and (details.raw_data.get("videos") or {}).get("video_list"):
                                video_pins.append(details)
                            else:
                                video_pins.append(p)

            for p in video_pins:
                pub_at = getattr(p, "published_at", None)
                if not pub_at and p.raw_data:
                    from pinterest_discovery import parse_pinterest_timestamp
                    raw_dt = p.raw_data.get("created_at") or p.raw_data.get("published_at")
                    pub_at = parse_pinterest_timestamp(raw_dt)

                cand = NatureCandidate(
                    source_id=p.pin_id,
                    platform="pinterest",
                    title=p.title or p.description or f"Scenic {category}",
                    canonical_url=p.canonical_url,
                    category=category,
                    search_keyword=keyword,
                    width=p.width,
                    height=p.height,
                    duration_seconds=float(p.duration_seconds) if p.duration_seconds else None,
                    thumbnail_url=p.thumbnail_url,
                    creator_attribution=p.raw_data.get("pinner", {}).get("username") if p.raw_data else None,
                    published_at=pub_at,
                    aspect_ratio=f"{p.width}x{p.height}" if p.width and p.height else None,
                    raw_metadata=p.raw_data,
                )
                candidates.append(cand)
        except Exception as e:
            logger.warning(f"Error querying Pinterest discovery: {e}")

        return candidates

    def _download_candidate_media(self, candidate: NatureCandidate, dest_path: Path) -> bool:
        """Download candidate video stream to dest_path using direct stream or PinterestDownloader."""
        if dest_path.exists() and dest_path.stat().st_size > 10000:
            return True

        # Check for direct video stream URL in raw_metadata
        direct_url = None
        if candidate.raw_metadata and isinstance(candidate.raw_metadata, dict):
            videos = candidate.raw_metadata.get("videos") or {}
            if isinstance(videos, dict):
                video_list = videos.get("video_list") or {}
                if isinstance(video_list, dict):
                    # Sort formats by resolution (highest first)
                    for fmt_key in ("V_1080P", "V_720P", "V_EXP7", "V_480P"):
                        if fmt_key in video_list and isinstance(video_list[fmt_key], dict):
                            u = video_list[fmt_key].get("url")
                            if u and u.startswith("http"):
                                direct_url = u
                                break
                    if not direct_url:
                        for fmt_info in video_list.values():
                            if isinstance(fmt_info, dict) and fmt_info.get("url"):
                                direct_url = fmt_info["url"]
                                break

        if direct_url:
            try:
                logger.info(f"Downloading direct Pinterest video stream from: {direct_url}")
                req = urllib.request.Request(
                    direct_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Referer": "https://www.pinterest.com/",
                    },
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    with open(dest_path, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                if dest_path.exists() and dest_path.stat().st_size > 10000:
                    logger.info(f"Direct stream download succeeded: {dest_path.stat().st_size} bytes")
                    return True
            except Exception as e:
                logger.warning(f"Direct stream download failed for {direct_url}: {e}, falling back to PinterestDownloader")

        vc = VideoCandidate(
            youtube_video_id=candidate.source_id,
            channel_id=f"pinterest_{candidate.category}",
            channel_name="Pinterest",
            title=candidate.title,
            youtube_url=candidate.canonical_url,
            published_at=None,
            duration_seconds=int(candidate.duration_seconds) if candidate.duration_seconds else None,
            is_short=False,
            is_live=False,
            platform="pinterest",
            source_id=candidate.source_id,
            canonical_url=candidate.canonical_url,
            search_keyword=candidate.search_keyword,
            width=candidate.width,
            height=candidate.height,
            thumbnail_url=candidate.thumbnail_url,
        )

        downloader = PinterestDownloader(self.config)
        try:
            downloaded = downloader.download_video(vc)
            if downloaded and Path(downloaded).exists():
                import shutil
                shutil.move(str(downloaded), str(dest_path))
                return True
        except Exception as e:
            logger.warning(f"PinterestDownloader failed for {candidate.canonical_url}: {e}")

        return False

    def _update_job_status(
        self,
        job_id: str,
        stage: JobStage,
        progress: int = 0,
        total_candidates: int = 0,
        processed_candidates: int = 0,
        rendered_reels: int = 0,
        current_category: Optional[str] = None,
        current_keyword: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update job table in SQLite."""
        job_data = {
            "job_id": job_id,
            "stage": stage.value,
            "progress": progress,
            "total_candidates": total_candidates,
            "processed_candidates": processed_candidates,
            "rendered_reels": rendered_reels,
            "current_category": current_category,
            "current_keyword": current_keyword,
            "error_message": error_message,
        }
        self.db.save_nature_job(job_data)
