"""Rendering engine for 'Nature Cinematic — Thought Reel' template."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from nature.models import CompositionMode, NatureTemplateConfig

logger = logging.getLogger(__name__)

# Recommended system font fallbacks
AVAILABLE_FONTS = [
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
]


class NatureTemplateRenderer:
    """Renders vertical cinematic nature Reels using FFmpeg with customizable templates."""

    def __init__(self, config: Optional[NatureTemplateConfig] = None):
        self.config = config or NatureTemplateConfig()
        # Verify font availability
        if not Path(self.config.font_path).exists():
            for f in AVAILABLE_FONTS:
                if Path(f).exists():
                    self.config.font_path = f
                    break

    def format_thought_text(self, text: str, max_width: int = 34, max_lines: Optional[int] = None) -> str:
        """Format thought into graceful, readable lines for vertical 9:16 reels."""
        if not text:
            return ""
        clean = text.strip().strip('"').strip("'")
        effective_max_lines = max_lines or self.config.max_lines

        # If text has explicit line breaks, preserve them and only wrap lines that exceed max_width
        if "\n" in clean:
            raw_lines = [l.strip() for l in clean.split("\n") if l.strip()]
            wrapped = []
            for line in raw_lines:
                if len(line) > max_width:
                    wrapped.extend(textwrap.wrap(line, width=max_width))
                else:
                    wrapped.append(line)
        else:
            wrapped = textwrap.wrap(clean, width=max_width)

        if effective_max_lines and len(wrapped) > effective_max_lines:
            wrapped = wrapped[:effective_max_lines]

        return "\n".join(wrapped)

    def _get_color_grade_filter(self, preset: str, intensity: float = 1.0) -> str:
        """Return FFmpeg video filter for subtle, restrained cinematic grading."""
        if intensity <= 0.0 or preset == "none":
            return "null"
        if preset == "restrained_warm":
            c = 1.0 + 0.04 * intensity
            s = 1.0 + 0.08 * intensity
            b = 0.01 * intensity
            return f"eq=contrast={c:.2f}:saturation={s:.2f}:brightness={b:.2f}"
        elif preset == "golden_hour":
            c = 1.0 + 0.06 * intensity
            s = 1.0 + 0.14 * intensity
            rs = 0.04 * intensity
            gs = 0.01 * intensity
            bs = -0.03 * intensity
            return f"eq=contrast={c:.2f}:saturation={s:.2f},colorbalance=rs={rs:.2f}:gs={gs:.2f}:bs={bs:.2f}"
        elif preset == "cool_mist":
            c = 1.0 + 0.03 * intensity
            s = 1.0 - 0.04 * intensity
            b = 0.02 * intensity
            bs = 0.03 * intensity
            gs = 0.01 * intensity
            return f"eq=contrast={c:.2f}:saturation={s:.2f}:brightness={b:.2f},colorbalance=bs={bs:.2f}:gs={gs:.2f}"
        return "null"

    def build_filter_complex(
        self,
        text_file_path: str,
        duration: float,
        fade_duration: float = 0.6,
        composition_mode: str = CompositionMode.CROP.value,
        color_preset: str = "restrained_warm",
        color_intensity: float = 1.0,
        enable_scrim: bool = False,
        letterbox_bars: bool = False,
        font_size: Optional[int] = None,
        line_spacing: Optional[int] = None,
        shadow_strength: Optional[float] = None,
        shadow_offset: Optional[int] = None,
        attribution_text: Optional[str] = None,
    ) -> str:
        """Construct the FFmpeg filter_complex string."""
        filters = []

        # 1. Composition / Framing to 1080x1920
        if composition_mode == CompositionMode.BLURRED_BACKGROUND.value:
            # Blurred background + centered fit video
            bg_chain = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];"
                "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
            )
            filters.append(bg_chain)
            current_tag = "[base]"
        elif composition_mode == CompositionMode.FIT_WITH_BACKGROUND.value or letterbox_bars:
            # Fit video with clean black bars
            fit_chain = (
                "[0:v]scale=w='if(gt(a,9/16),1080,-2)':h='if(gt(a,9/16),-2,1920)',"
                "pad=1080:1920:(1080-iw)/2:(1920-ih)/2:black[base]"
            )
            filters.append(fit_chain)
            current_tag = "[base]"
        else:
            # Default CROP: Scale to fill 1080x1920 without stretching, center crop
            crop_chain = (
                "[0:v]scale=w='if(gt(a,9/16),-2,1080)':h='if(gt(a,9/16),1920,-2)',"
                "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2[base]"
            )
            filters.append(crop_chain)
            current_tag = "[base]"

        # 2. Color grading
        color_filter = self._get_color_grade_filter(color_preset, intensity=color_intensity)
        if color_filter != "null":
            filters.append(f"{current_tag}{color_filter}[graded]")
            current_tag = "[graded]"

        # 3. Text-safe subtle scrim (only if enabled)
        if enable_scrim:
            scrim_filter = "drawbox=y=(h-380)/2+80:w=iw:h=380:color=black@0.32:t=fill"
            filters.append(f"{current_tag}{scrim_filter}[scrim]")
            current_tag = "[scrim]"

        # 4. Text burn with alpha fade
        fade_out_start = max(0.0, duration - fade_duration)
        alpha_expr = f"if(lt(t,{fade_duration}),t/{fade_duration},if(gt(t,{fade_out_start:.2f}),({duration:.2f}-t)/{fade_duration},1))"

        # Safe drawtext
        font_path_escaped = self.config.font_path.replace(":", "\\:")
        text_file_escaped = text_file_path.replace(":", "\\:")

        eff_font_size = font_size or self.config.font_size
        eff_line_spacing = line_spacing if line_spacing is not None else self.config.line_spacing
        eff_shadow_strength = shadow_strength if shadow_strength is not None else self.config.shadow_strength
        eff_shadow_offset = shadow_offset if shadow_offset is not None else self.config.shadow_offset

        drawtext_params = [
            f"fontfile='{font_path_escaped}'",
            f"textfile='{text_file_escaped}'",
            f"fontsize={eff_font_size}",
            "fontcolor=white",
            "x=(w-text_w)/2",
            f"y={self.config.text_position_y}",
            f"line_spacing={eff_line_spacing}",
            f"shadowcolor=black@{eff_shadow_strength:.2f}",
            f"shadowx={eff_shadow_offset}",
            f"shadowy={eff_shadow_offset}",
            f"alpha='{alpha_expr}'",
        ]
        text_filter = f"drawtext={':'.join(drawtext_params)}"
        filters.append(f"{current_tag}{text_filter}[vtext]")
        current_tag = "[vtext]"

        # Optional creator attribution
        if attribution_text and self.config.show_attribution:
            attr_escaped = attribution_text.replace(":", "\\:").replace("'", "\\'")
            attr_filter = (
                f"drawtext=fontfile='{font_path_escaped}':text='{attr_escaped}':"
                f"fontsize=24:fontcolor=white@0.60:x=(w-text_w)/2:y=h-140:"
                f"shadowcolor=black@0.5:shadowx=1:shadowy=1:alpha='{alpha_expr}'"
            )
            filters.append(f"{current_tag}{attr_filter}[vattr]")
            current_tag = "[vattr]"

        # 5. Gentle video fade in and fade out
        fade_in = f"fade=t=in:st=0:d={fade_duration}"
        fade_out = f"fade=t=out:st={fade_out_start:.2f}:d={fade_duration}"
        filters.append(f"{current_tag}{fade_in},{fade_out}[vout]")

        return ";".join(filters)

    def _has_audio_stream(self, video_path: Path) -> bool:
        """Check if video file has at least one audio stream."""
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(video_path),
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            return "audio" in res.stdout
        except Exception:
            return False

    def render_reel(
        self,
        input_video_path: str | Path,
        thought_text: str,
        output_reel_path: str | Path,
        target_duration: Optional[float] = None,
        composition_mode: Optional[str] = None,
        color_preset: Optional[str] = None,
        color_intensity: Optional[float] = None,
        font_path: Optional[str] = None,
        font_size: Optional[int] = None,
        line_spacing: Optional[int] = None,
        shadow_strength: Optional[float] = None,
        source_audio_volume: Optional[float] = None,
        music_path: Optional[str | Path] = None,
        music_volume: Optional[float] = None,
        enable_scrim: Optional[bool] = None,
        template_config: Optional[NatureTemplateConfig] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Render the complete nature reel to output_reel_path.

        Validates output media file upon completion.
        """
        if template_config:
            self.config = template_config

        input_path = Path(input_video_path)
        if not input_path.exists():
            return False, f"Input video file does not exist: {input_video_path}"

        out_path = Path(output_reel_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        mode = composition_mode or self.config.composition_mode
        color = color_preset or self.config.color_grade_preset
        intensity = color_intensity if color_intensity is not None else self.config.color_grading_intensity
        duration = target_duration or self.config.target_duration
        scrim = enable_scrim if enable_scrim is not None else self.config.enable_scrim

        src_vol = source_audio_volume if source_audio_volume is not None else self.config.source_audio_volume
        bg_music = music_path or self.config.music_path
        bg_music_vol = music_volume if music_volume is not None else self.config.music_volume

        if font_path and Path(font_path).exists():
            self.config.font_path = font_path
        if font_size:
            self.config.font_size = font_size
        if line_spacing is not None:
            self.config.line_spacing = line_spacing
        if shadow_strength is not None:
            self.config.shadow_strength = shadow_strength

        # Dynamic font scaling if text is long (6+ lines)
        formatted_text = self.format_thought_text(thought_text, max_lines=self.config.max_lines)
        line_count = len(formatted_text.split("\n"))
        effective_font_size = self.config.font_size
        if line_count >= 7:
            effective_font_size = min(effective_font_size, 42)
        elif line_count >= 5:
            effective_font_size = min(effective_font_size, 46)

        # Write formatted text to temporary file
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as tf:
            tf.write(formatted_text)
            text_file_path = tf.name

        try:
            video_filter_complex = self.build_filter_complex(
                text_file_path=text_file_path,
                duration=duration,
                fade_duration=self.config.fade_duration,
                composition_mode=mode,
                color_preset=color,
                color_intensity=intensity,
                enable_scrim=scrim,
                letterbox_bars=self.config.letterbox_bars,
                font_size=effective_font_size,
                line_spacing=self.config.line_spacing,
                shadow_strength=self.config.shadow_strength,
                shadow_offset=self.config.shadow_offset,
                attribution_text=self.config.attribution_text if self.config.show_attribution else None,
            )

            # Determine audio streams and mixing
            has_source_audio = self._has_audio_stream(input_path)
            has_bg_music = bg_music and Path(bg_music).exists()

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                "0",
                "-t",
                str(duration),
                "-i",
                str(input_path),
            ]

            filter_chains = [video_filter_complex]
            audio_map = []

            if has_bg_music:
                cmd.extend(["-stream_loop", "-1", "-t", str(duration), "-i", str(bg_music)])
                if has_source_audio:
                    audio_filter = (
                        f"[0:a]volume={src_vol:.2f}[a0];"
                        f"[1:a]volume={bg_music_vol:.2f}[a1];"
                        f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]"
                    )
                    filter_chains.append(audio_filter)
                    audio_map = ["-map", "[aout]"]
                else:
                    audio_filter = f"[1:a]volume={bg_music_vol:.2f}[aout]"
                    filter_chains.append(audio_filter)
                    audio_map = ["-map", "[aout]"]
            elif has_source_audio:
                if abs(src_vol - 1.0) > 0.01:
                    audio_filter = f"[0:a]volume={src_vol:.2f}[aout]"
                    filter_chains.append(audio_filter)
                    audio_map = ["-map", "[aout]"]
                else:
                    audio_map = ["-map", "0:a"]
            else:
                audio_map = ["-map", "0:a?"]

            combined_filters = ";".join(filter_chains)

            cmd.extend([
                "-filter_complex",
                combined_filters,
                "-map",
                "[vout]",
            ])
            cmd.extend(audio_map)
            cmd.extend([
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "21",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(self.config.fps),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(out_path),
            ])

            logger.info(f"Rendering Nature Reel: {out_path.name} (mode: {mode})")
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)

            if res.returncode != 0:
                logger.error(f"FFmpeg render failed: {res.stderr}")
                return False, f"FFmpeg render error: {res.stderr[-300:]}"

            # Validate rendered output
            is_valid, val_err = self.validate_output_reel(out_path, min_duration=duration - 1.5)
            if not is_valid:
                return False, f"Output validation failed: {val_err}"

            return True, None

        except subprocess.TimeoutExpired:
            return False, "FFmpeg rendering timed out after 120 seconds"
        except Exception as e:
            return False, f"Rendering exception: {str(e)}"
        finally:
            if os.path.exists(text_file_path):
                try:
                    os.remove(text_file_path)
                except Exception:
                    pass

    def generate_thumbnail(self, video_path: str | Path, thumbnail_path: str | Path, timestamp: float = 2.0) -> bool:
        """Extract a high-quality thumbnail image from rendered reel."""
        out_thumb = Path(thumbnail_path)
        out_thumb.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(out_thumb),
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            return res.returncode == 0 and out_thumb.exists()
        except Exception as e:
            logger.error(f"Thumbnail generation error: {e}")
            return False

    def validate_output_reel(self, reel_path: str | Path, min_duration: float = 4.0) -> Tuple[bool, Optional[str]]:
        """Verify that the rendered video exists, has non-zero size, 1080x1920 resolution, and expected duration."""
        p = Path(reel_path)
        if not p.exists() or p.stat().st_size < 10000:
            return False, "Rendered file does not exist or is too small (<10KB)"

        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(p),
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if res.returncode != 0:
                return False, "ffprobe failed to read rendered reel"

            info = json.loads(res.stdout)
            streams = info.get("streams", [])
            v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            if not v_stream:
                return False, "No video stream in rendered reel"

            w = int(v_stream.get("width", 0))
            h = int(v_stream.get("height", 0))
            dur = float(info.get("format", {}).get("duration", 0.0))

            if w != 1080 or h != 1920:
                return False, f"Rendered resolution {w}x{h} does not match required 1080x1920 canvas"
            if dur < min_duration:
                return False, f"Rendered duration {dur:.1f}s is shorter than minimum {min_duration:.1f}s"

            return True, None
        except Exception as e:
            return False, f"Validation probe error: {str(e)}"
