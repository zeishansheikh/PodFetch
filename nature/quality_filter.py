from __future__ import annotations

import json
import logging
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageStat
from nature.models import NatureCandidate, NatureProfile, NatureQualityScore
from nature.profile import ProfileManager

logger = logging.getLogger(__name__)


class NatureQualityFilter:
    """Evaluates video candidates on technical metrics, visual clarity, scenic relevance,

    and strict rights/reuse eligibility.
    """

    def __init__(self, profile: Optional[NatureProfile] = None):
        self.profile = profile or NatureProfile()

    def probe_video_file(self, video_path: str | Path) -> Dict[str, Any]:
        """Run ffprobe to extract stream metadata."""
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
            if res.returncode != 0:
                logger.warning(f"ffprobe failed for {video_path}: {res.stderr}")
                return {}
            return json.loads(res.stdout)
        except Exception as e:
            logger.error(f"Error running ffprobe on {video_path}: {e}")
            return {}

    def verify_decode_integrity(self, video_path: str | Path, max_check_seconds: int = 15) -> Tuple[bool, Optional[str]]:
        """Verify that the video file can be decoded without fatal stream errors."""
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-t",
            str(max_check_seconds),
            "-i",
            str(video_path),
            "-f",
            "null",
            "-",
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            if res.returncode != 0:
                err_summary = res.stderr.strip()[:200] or "Decode failed"
                return False, f"Stream corruption or decode error: {err_summary}"
            return True, None
        except subprocess.TimeoutExpired:
            return False, "Decode verification timed out"
        except Exception as e:
            return False, f"Integrity check exception: {str(e)}"

    def extract_sample_frames(
        self, video_path: str | Path, num_frames: int = 3, duration: float = 10.0
    ) -> List[Image.Image]:
        """Extract evenly-spaced sample frames using ffmpeg into PIL Images."""
        frames: List[Image.Image] = []
        if duration <= 1.0:
            timestamps = [0.5]
        else:
            step = duration / (num_frames + 1)
            timestamps = [step * (i + 1) for i in range(num_frames)]

        for ts in timestamps:
            cmd = [
                "ffmpeg",
                "-ss",
                f"{ts:.2f}",
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-",
            ]
            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
                if res.returncode == 0 and res.stdout:
                    import io

                    img = Image.open(io.BytesIO(res.stdout)).convert("RGB")
                    frames.append(img)
            except Exception as e:
                logger.debug(f"Failed to extract frame at {ts}s: {e}")

        return frames

    def analyze_visual_clarity(self, frames: List[Image.Image]) -> Tuple[float, bool, bool, List[str]]:
        """Analyze sharpness, black frames, and contrast across sampled frames.

        Returns (clarity_score, has_black_frames, has_low_contrast, issues).
        """
        if not frames:
            return 40.0, False, False, ["Unable to sample video frames for visual inspection"]

        issues: List[str] = []
        scores: List[float] = []
        black_frame_count = 0

        for frame in frames:
            stat = ImageStat.Stat(frame)
            # 1. Mean brightness (0-255)
            mean_brightness = sum(stat.mean[:3]) / 3.0
            # 2. Standard deviation / RMS contrast
            contrast = sum(stat.stddev[:3]) / 3.0

            # Check if nearly black or completely blown out
            if mean_brightness < 12.0:
                black_frame_count += 1
                issues.append("Clip contains pitch black or severely underexposed frames")
            elif mean_brightness > 245.0:
                issues.append("Clip contains overexposed/blown out white frames")

            # 3. Simple edge sharpness estimate via high-pass/gradient difference
            gray = frame.convert("L")
            # Downsample slightly for fast processing
            small = gray.resize((240, 240), Image.Resampling.BILINEAR)
            pixels = list(small.getdata())
            w, h = small.size

            # Horizontal & vertical diff variance (edge energy)
            diffs = []
            for y in range(0, h - 1, 2):
                row_offset = y * w
                next_row_offset = (y + 1) * w
                for x in range(0, w - 1, 2):
                    dx = abs(pixels[row_offset + x] - pixels[row_offset + x + 1])
                    dy = abs(pixels[row_offset + x] - pixels[next_row_offset + x])
                    diffs.append(dx + dy)

            edge_energy = sum(diffs) / len(diffs) if diffs else 0.0

            # Score this frame (contrast + edge energy)
            # Edge energy for clear nature footage is typically 12-40
            frame_sharpness = min(100.0, (edge_energy / 25.0) * 80.0)
            frame_contrast = min(100.0, (contrast / 50.0) * 100.0)
            frame_score = (frame_sharpness * 0.6) + (frame_contrast * 0.4)
            scores.append(frame_score)

        has_black = black_frame_count > 0
        has_low_contrast = any(s < 30.0 for s in scores)
        avg_score = sum(scores) / len(scores) if scores else 50.0

        if avg_score < 35.0:
            issues.append("Video exhibits excessive blur, low contrast, or heavy compression artefacts")

        return round(avg_score, 1), has_black, has_low_contrast, issues

    def analyze_scenic_color_distribution(self, frames: List[Image.Image]) -> Tuple[float, bool]:
        """Check for organic nature hues (greens, sky/water blues, warm sunset golds, earth tones)."""
        if not frames:
            return 50.0, True

        nature_hue_matches = 0
        total_samples = 0

        for frame in frames:
            # Resize small for fast color distribution
            small = frame.resize((80, 80), Image.Resampling.NEAREST)
            for r, g, b in small.getdata():
                total_samples += 1
                # Green foliage: g > r and g > b
                if g > r + 15 and g > b + 15:
                    nature_hue_matches += 1
                # Blue sky / water: b > r and b >= g
                elif b > r + 15 and b >= g:
                    nature_hue_matches += 1
                # Golden hour / warm sunset: r high, g medium, b low
                elif r > 120 and g > 70 and r > b + 30:
                    nature_hue_matches += 1
                # Earth / mountain rock / misty neutral: balanced with texture
                elif abs(r - g) < 20 and abs(g - b) < 20 and 40 < r < 210:
                    nature_hue_matches += 0.5

        ratio = (nature_hue_matches / total_samples) if total_samples > 0 else 0.5
        score = min(100.0, ratio * 150.0)
        is_scenic = score >= 45.0
        return round(score, 1), is_scenic

    def calculate_recency_score(
        self,
        published_at: Optional[str],
        recency_preference: str = "any",
        strict_recency: bool = False,
    ) -> Tuple[float, str, Optional[str]]:
        """Calculate recency score and status based on genuine published_at timestamp.

        Returns (recency_score, recency_status, rejection_reason_or_None).
        """
        now = datetime.now(timezone.utc)
        if not published_at:
            if strict_recency and recency_preference != "any":
                return 40.0, "unknown", "Publication date is unknown and strict recency is required"
            return 70.0, "unknown", None

        try:
            pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if not pub_dt.tzinfo:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            age_days = (now - pub_dt).total_seconds() / 86400.0

            if age_days <= 90:
                status = "very_recent"
                score = 100.0
            elif age_days <= 180:
                status = "recent"
                score = 90.0
            elif age_days <= 365:
                status = "moderate"
                score = 75.0
            else:
                status = "older"
                score = 55.0

            rejection = None
            if recency_preference == "last_3_months" and age_days > 90:
                if strict_recency:
                    rejection = f"Video is {age_days:.0f} days old (exceeds 3 months preference)"
                else:
                    score = 40.0
            elif recency_preference == "last_6_months" and age_days > 180:
                if strict_recency:
                    rejection = f"Video is {age_days:.0f} days old (exceeds 6 months preference)"
                else:
                    score = 45.0
            elif recency_preference == "last_12_months" and age_days > 365:
                if strict_recency:
                    rejection = f"Video is {age_days:.0f} days old (exceeds 12 months preference)"
                else:
                    score = 50.0

            return score, status, rejection
        except Exception:
            if strict_recency and recency_preference != "any":
                return 40.0, "unknown", "Publication date is invalid and strict recency is required"
            return 70.0, "unknown", None

    def evaluate_pre_download(
        self,
        candidate: NatureCandidate,
        recency_preference: str = "any",
        strict_recency: bool = False,
        preferred_orientation: str = "vertical_9_16",
        min_quality_score: Optional[float] = None,
    ) -> Tuple[float, bool, List[str]]:
        """Rank and gate candidates before downloading media file using available metadata.

        Returns (pre_download_score, is_eligible, rejection_reasons).
        """
        rejection_reasons: List[str] = []
        is_eligible = True
        threshold = min_quality_score if min_quality_score is not None else self.profile.min_quality_score

        # 1. Video validation check
        raw = candidate.raw_metadata or {}
        if raw:
            is_vid = bool(raw.get("is_video"))
            has_vid_list = bool((raw.get("videos") or {}).get("video_list"))
            has_media_vid = bool((raw.get("media") or {}).get("media_type") in ("video", "video_list"))
            has_story = bool(raw.get("story_pin_data"))
            if not (is_vid or has_vid_list or has_media_vid or has_story):
                return 0.0, False, ["Candidate is not a video Pin"]

        # 2. Prohibited & negative terms check
        prof_mgr = ProfileManager(self.profile)
        is_ex, ex_reason = prof_mgr.is_title_or_desc_excluded(candidate.title)
        if is_ex:
            return 0.0, False, [ex_reason or "Contains prohibited or irrelevant content"]

        # 3. Stream availability check
        stream_score = 70.0
        videos = raw.get("videos") or {}
        media = raw.get("media") or {}
        video_list = videos.get("video_list") if isinstance(videos, dict) else {}
        if isinstance(video_list, dict) and video_list:
            stream_score = 100.0
        elif isinstance(media, dict) and media.get("video_list"):
            stream_score = 90.0

        # 4. Resolution & Aspect Ratio check
        w = candidate.width or 0
        h = candidate.height or 0
        res_score = 70.0
        orient_score = 75.0
        if w > 0 and h > 0:
            candidate.aspect_ratio = f"{w}x{h}"
            if w < 360 or h < 360:
                is_eligible = False
                rejection_reasons.append(f"Resolution {w}x{h} is too low for a vertical reel")

            max_dim = max(w, h)
            if max_dim >= 1080:
                res_score = 100.0
            elif max_dim >= 720:
                res_score = 88.0
            elif max_dim >= 480:
                res_score = 72.0
            else:
                res_score = 50.0

            ratio = w / h if h > 0 else 1.0
            target_vert = 9.0 / 16.0  # 0.5625
            if preferred_orientation == "vertical_9_16":
                if abs(ratio - target_vert) < 0.1:
                    orient_score = 100.0  # 9:16 vertical
                elif ratio < 0.8:
                    orient_score = 90.0   # Portrait vertical
                elif abs(ratio - 1.0) < 0.15:
                    orient_score = 75.0   # Square
                else:
                    orient_score = 60.0   # Landscape
            elif preferred_orientation == "landscape":
                orient_score = 100.0 if ratio > 1.2 else 60.0
            else:
                orient_score = 85.0

        # 5. Duration check
        dur = candidate.duration_seconds
        dur_score = 75.0
        if dur is not None:
            if dur < 3.5:
                is_eligible = False
                rejection_reasons.append(f"Duration {dur:.1f}s is too short")
            elif dur > 180.0:
                is_eligible = False
                rejection_reasons.append(f"Duration {dur:.1f}s is too long")
            elif 8.0 <= dur <= 25.0:
                dur_score = 100.0
            elif 5.0 <= dur <= 45.0:
                dur_score = 85.0
            else:
                dur_score = 70.0

        # 6. Recency check
        recency_score, recency_status, rec_rej = self.calculate_recency_score(
            candidate.published_at,
            recency_preference=recency_preference,
            strict_recency=strict_recency,
        )
        if rec_rej:
            is_eligible = False
            rejection_reasons.append(rec_rej)

        candidate.recency_status = recency_status

        pre_download_score = round(
            (stream_score * 0.25)
            + (res_score * 0.25)
            + (orient_score * 0.20)
            + (dur_score * 0.15)
            + (recency_score * 0.15),
            1,
        )
        candidate.pre_score = pre_download_score

        if pre_download_score < threshold and is_eligible:
            is_eligible = False
            rejection_reasons.append(f"Pre-download score {pre_download_score:.1f} is below threshold {threshold:.1f}")

        return pre_download_score, is_eligible, rejection_reasons

    def evaluate_candidate(
        self,
        candidate: NatureCandidate,
        local_video_path: Optional[str | Path] = None,
        already_processed_ids: Optional[set] = None,
        recency_preference: str = "any",
        strict_recency: bool = False,
        preferred_orientation: str = "vertical_9_16",
    ) -> NatureQualityScore:
        """Complete evaluation of candidate metadata and media file."""
        rejection_reasons: List[str] = []
        is_eligible = True

        # 1. Deduplication Gate
        if already_processed_ids and candidate.source_id in already_processed_ids:
            is_eligible = False
            rejection_reasons.append(f"Duplicate candidate: source ID {candidate.source_id} already processed")

        # 2. Excluded terms in title / description
        prof_mgr = ProfileManager(self.profile)
        is_ex, ex_reason = prof_mgr.is_title_or_desc_excluded(candidate.title)
        if is_ex:
            is_eligible = False
            rejection_reasons.append(ex_reason or "Title/metadata contains prohibited content")

        # Pre-download score calculation
        pre_score, pre_eligible, pre_reasons = self.evaluate_pre_download(
            candidate,
            recency_preference=recency_preference,
            strict_recency=strict_recency,
            preferred_orientation=preferred_orientation,
        )
        if not pre_eligible:
            is_eligible = False
            rejection_reasons.extend(pre_reasons)

        # If no local file yet, return initial pre-download metadata triage
        if not local_video_path or not Path(local_video_path).exists():
            meta_score = NatureQualityScore(
                overall_score=pre_score if is_eligible else 0.0,
                technical_score=70.0,
                visual_clarity_score=70.0,
                vertical_suitability_score=80.0,
                scenic_relevance_score=75.0,
                recency_score=70.0,
                pre_download_score=pre_score,
                recency_status=candidate.recency_status or "unknown",
                is_scenic=True,
                has_subject=True,
                is_eligible=is_eligible,
                rejection_reasons=rejection_reasons,
            )
            candidate.quality_score = meta_score
            if not is_eligible:
                candidate.eligibility_status = "REJECTED"
                candidate.rejection_reason = "; ".join(rejection_reasons)
            else:
                candidate.eligibility_status = "ELIGIBLE"
                candidate.rejection_reason = None
            return meta_score

        # 3. File & Stream Inspection
        probe_data = self.probe_video_file(local_video_path)
        streams = probe_data.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        format_info = probe_data.get("format", {})

        if not video_stream:
            is_eligible = False
            rejection_reasons.append("No valid video stream detected in media file")
            score = NatureQualityScore(
                overall_score=0.0,
                is_eligible=False,
                rejection_reasons=rejection_reasons,
            )
            candidate.quality_score = score
            candidate.eligibility_status = "REJECTED"
            candidate.rejection_reason = "; ".join(rejection_reasons)
            return score

        # Decode integrity check
        ok, decode_err = self.verify_decode_integrity(local_video_path)
        if not ok:
            is_eligible = False
            rejection_reasons.append(decode_err or "Video stream decode failed")

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        duration = float(video_stream.get("duration") or format_info.get("duration") or 0.0)

        # FPS calculation
        fps_str = video_stream.get("r_frame_rate", "30/1")
        try:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        except Exception:
            fps = 30.0

        # Update candidate metrics
        candidate.width = width
        candidate.height = height
        candidate.duration_seconds = duration
        candidate.fps = round(fps, 2)
        bitrate = int(format_info.get("bit_rate") or video_stream.get("bit_rate") or 0)
        candidate.bitrate = bitrate

        # Technical checks & bounds
        tech_issues = []
        if width < 480 or height < 480:
            tech_issues.append(f"Resolution {width}x{height} is too low (minimum 480p)")
        if duration < 4.0:
            tech_issues.append(f"Duration {duration:.1f}s is too short (minimum 4s)")
        if duration > 180.0:
            tech_issues.append(f"Duration {duration:.1f}s exceeds maximum limit of 180s")
        if fps < 18.0:
            tech_issues.append(f"Frame rate {fps:.1f} FPS is unnaturally low")

        if tech_issues:
            is_eligible = False
            rejection_reasons.extend(tech_issues)

        # Technical Score (0-100)
        # Higher resolution, healthy duration, good fps
        res_factor = min(100.0, (max(width, height) / 1920.0) * 100.0)
        fps_factor = min(100.0, (fps / 30.0) * 100.0)
        dur_factor = 100.0 if 7.0 <= duration <= 30.0 else (80.0 if 4.0 <= duration <= 60.0 else 50.0)
        tech_score = round((res_factor * 0.5) + (fps_factor * 0.3) + (dur_factor * 0.2), 1)

        # Vertical Suitability Score (0-100)
        aspect_ratio = width / height if height > 0 else 1.0
        target_vertical_ratio = 9.0 / 16.0  # 0.5625
        if abs(aspect_ratio - target_vertical_ratio) < 0.08:
            # Native 9:16 vertical
            vert_score = 100.0
        elif aspect_ratio < 0.85:
            # Tall vertical (e.g. 4:5 or 3:4)
            vert_score = 90.0
        elif abs(aspect_ratio - 1.0) < 0.15:
            # 1:1 Square
            vert_score = 80.0
        elif aspect_ratio > 1.3:
            # Landscape (16:9 ~ 1.78)
            # Fully supported via crop, fit-with-background, or blurred-background
            vert_score = 75.0
        else:
            vert_score = 70.0

        # Sample frame visual inspection
        frames = self.extract_sample_frames(local_video_path, num_frames=3, duration=duration)
        clarity_score, has_black, has_low_contrast, clarity_issues = self.analyze_visual_clarity(frames)
        if clarity_issues:
            # If severe blur or black frames, reject
            if has_black or clarity_score < 30.0:
                is_eligible = False
                rejection_reasons.extend(clarity_issues)

        # Scenic relevance
        scenic_score, is_scenic = self.analyze_scenic_color_distribution(frames)
        if not is_scenic and scenic_score < 25.0:
            rejection_reasons.append("Visual color distribution does not match natural scenic environment")

        # Overall composite score with recency factor
        rec_score = getattr(candidate, "recency_score", 70.0) if hasattr(candidate, "recency_score") else 70.0
        if candidate.quality_score and candidate.quality_score.recency_score:
            rec_score = candidate.quality_score.recency_score
        elif candidate.published_at:
            rec_score = 90.0 if "recent" in (candidate.recency_status or "") else 75.0

        overall_score = round(
            (tech_score * 0.25)
            + (clarity_score * 0.25)
            + (scenic_score * 0.25)
            + (vert_score * 0.15)
            + (rec_score * 0.10),
            1,
        )

        # Threshold check
        if overall_score < self.profile.min_quality_score:
            rejection_reasons.append(
                f"Overall score {overall_score:.1f} is below minimum threshold {self.profile.min_quality_score:.1f}"
            )
            is_eligible = False

        result = NatureQualityScore(
            overall_score=overall_score if is_eligible else 0.0,
            technical_score=tech_score,
            visual_clarity_score=clarity_score,
            vertical_suitability_score=vert_score,
            scenic_relevance_score=scenic_score,
            recency_score=rec_score,
            pre_download_score=pre_score,
            recency_status=candidate.recency_status or "unknown",
            is_scenic=is_scenic,
            has_subject=True,
            is_eligible=is_eligible,
            rejection_reasons=rejection_reasons,
        )

        candidate.quality_score = result
        if not is_eligible:
            candidate.eligibility_status = "REJECTED"
            candidate.rejection_reason = "; ".join(rejection_reasons)
        else:
            candidate.eligibility_status = "ELIGIBLE"
            candidate.rejection_reason = None

        return result
