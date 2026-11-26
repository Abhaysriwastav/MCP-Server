"""Composable FFmpeg video editing & dual-rendition export pipeline."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from video_mcp.media.ffmpeg_runner import FFmpegRunner, sha256_file
from video_mcp.media.transcriber import Transcriber, generate_srt
from video_mcp.media.voice_cloner import VoiceCloner
from video_mcp.models import (
    AudioNormalizeOp,
    AutoCaptionOp,
    BurnSubtitlesOp,
    EditOperation,
    FadeOp,
    OutputProfile,
    ReframeOp,
    RenderedArtifact,
    ScaleOp,
    SourceAsset,
    SpeedOp,
    TextOverlayOp,
    TranscriptSegment,
    TrimOp,
    VoiceCloneOp,
    WatermarkOp,
)

ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def _escape_filter_path(path: Path) -> str:
    """Escape a filesystem path for FFmpeg's `subtitles=` filtergraph option."""
    return (
        str(path)
        .replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


_SRT_TS_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def _parse_srt_cues(srt_text: str) -> list[tuple[float, float, str]]:
    """Parse UTF-8 SRT text into `(start_sec, end_sec, text)` tuples."""
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\r?\n\s*\r?\n", srt_text.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        ts_line = lines[1] if _SRT_TS_RE.search(lines[1]) else lines[0]
        match = _SRT_TS_RE.search(ts_line)
        if not match:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in match.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        text_lines = lines[2:] if ts_line == lines[1] else lines[1:]
        text = " ".join(text_lines).strip()
        if text:
            cues.append((start, max(end, start + 0.1), text))
    return cues


def _subtitle_force_style(font_size: int = 20, margin_v: int = 55) -> str:
    """Return ASS force_style string legible across both 16:9 and 9:16 exports."""
    return (
        f"FontName=Arial,FontSize={font_size},Bold=1,"
        f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,"
        f"BorderStyle=1,Outline=2,Shadow=1,MarginV={margin_v},Alignment=2"
    )


def _atempo_chain(factor: float) -> list[str]:
    """Build chained atempo filters because FFmpeg atempo accepts [0.5, 2.0] per stage."""
    filters: list[str] = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    return filters


def _reframe_filter(width: int, height: int, mode: str = "crop") -> str:
    if mode == "pad":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )


class VideoPipeline:
    """Executes edit operations, renders 16:9 / 9:16 / both outputs, thumbnails, and manifests."""

    def __init__(
        self,
        runner: FFmpegRunner,
        workspace_dir: Path,
        transcriber: Transcriber | None = None,
        voice_cloner: VoiceCloner | None = None,
        default_max_words_per_line: int = 6,
    ) -> None:
        self.runner = runner
        self.workspace_dir = workspace_dir
        self.transcriber = transcriber
        self.voice_cloner = voice_cloner
        self.default_max_words_per_line = default_max_words_per_line

    async def render_job(
        self,
        job_id: str,
        sources: list[SourceAsset],
        operations: list[EditOperation],
        output_profile: OutputProfile,
        watermark_sources: dict[str, SourceAsset] | None = None,
        voice_reference_sources: dict[str, SourceAsset] | None = None,
        progress_cb: Callable[[float, str], None] | None = None,
    ) -> list[RenderedArtifact]:
        """Run the full editing pipeline for a job and return rendered media + metadata artifacts."""
        if not sources:
            raise ValueError("At least one source asset is required to render a job.")

        def _report(pct: float, stage: str) -> None:
            if progress_cb is not None:
                progress_cb(min(100.0, max(0.0, pct)), stage)

        def _sub_progress(start_pct: float, end_pct: float, stage: str) -> Callable[[float], None]:
            span = end_pct - start_pct
            return lambda frac: _report(start_pct + span * frac, stage)

        job_dir = self.workspace_dir / "renders" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir = self.workspace_dir / "thumbnails" / job_id
        thumb_dir.mkdir(parents=True, exist_ok=True)

        _report(2.0, "Preparing source")
        # Step 1: Prepare base input (single clip or concatenated multi-clip)
        if len(sources) == 1:
            base_input = Path(sources[0].local_path)
            has_audio = bool(sources[0].probe.get("has_audio", False))
            base_duration = float(sources[0].probe.get("duration_sec") or 0.0)
        else:
            base_input = job_dir / "concat_base.mp4"
            _report(5.0, "Concatenating clips")
            has_audio = await self._concat_sources(sources, base_input)
            base_duration = sum(float(s.probe.get("duration_sec") or 0.0) for s in sources)

        # Step 2: Separate voice_clone and auto_caption from pre-caption edit ops
        # so trim/concat/speed run first, then transcription, AI voice replacement,
        # and SRT generation run on the cut clip (timestamps at 00:00:00,000) before
        # splitting into 16:9 and 9:16.
        caption_ops = [op for op in operations if isinstance(op, AutoCaptionOp)]
        voice_ops = [op for op in operations if isinstance(op, VoiceCloneOp)]
        pre_caption_ops = [
            op for op in operations if not isinstance(op, (AutoCaptionOp, VoiceCloneOp))
        ]
        artifacts: list[RenderedArtifact] = []

        if pre_caption_ops:
            pre_caption_path = job_dir / (
                "pre_caption.mp4" if (caption_ops or voice_ops) else "master_edited.mp4"
            )
            _report(10.0, "Applying edits")
            await self._apply_operations(
                input_path=base_input,
                output_path=pre_caption_path,
                operations=pre_caption_ops,
                has_audio=has_audio,
                watermark_sources=watermark_sources or {},
                progress_cb=_sub_progress(10.0, 30.0, "Applying edits"),
                duration_sec=base_duration or None,
            )
        else:
            pre_caption_path = base_input

        cached_segments: list[TranscriptSegment] | None = None
        if caption_ops or (voice_ops and not voice_ops[-1].script_text):
            if self.transcriber is None:
                raise RuntimeError("Transcription requested but Transcriber is not configured.")
            _report(32.0, "Transcribing audio (Whisper)")
            cached_segments = await self.transcriber.transcribe_media(
                pre_caption_path, word_timestamps=True
            )

        voiced_path = pre_caption_path
        if voice_ops:
            if self.voice_cloner is None:
                raise RuntimeError("VoiceCloneOp requested but VoiceCloner is not configured.")
            v_op = voice_ops[-1]
            script_text = (v_op.script_text or "").strip()
            if not script_text and cached_segments:
                script_text = " ".join(s.text.strip() for s in cached_segments if s.text.strip())
            if not script_text:
                raise RuntimeError("VoiceCloneOp found no spoken text or script_text to synthesize.")

            ref_audio_path: Path | None = None
            if v_op.reference_audio_source_id:
                ref_src = (voice_reference_sources or {}).get(v_op.reference_audio_source_id)
                if ref_src is None:
                    raise ValueError(
                        f"Voice reference source not found: {v_op.reference_audio_source_id}"
                    )
                ref_audio_path = Path(ref_src.local_path)
            elif self.voice_cloner.settings.voice_provider in {"coqui", "omnivoice"} and has_audio:
                ref_audio_path = await self.voice_cloner.extract_reference_sample(
                    pre_caption_path, job_dir / "voice_reference.wav"
                )

            _report(40.0, "Cloning AI voice")
            dub_wav = job_dir / "ai_voice_dub.wav"
            await self.voice_cloner.synthesize(
                text=script_text,
                output_path=dub_wav,
                reference_audio_path=ref_audio_path,
                voice_id=v_op.voice_id,
                language=v_op.language,
            )
            artifacts.append(
                self._make_artifact(
                    kind="voice_dub",
                    path=dub_wav,
                    mime_type="audio/wav",
                    metadata={
                        "provider": self.voice_cloner.settings.voice_provider,
                        "language": v_op.language,
                    },
                )
            )

            voiced_path = job_dir / ("pre_caption_voiced.mp4" if caption_ops else "master_edited.mp4")
            _report(45.0, "Replacing audio with AI voice")
            await self._apply_voice_dub(
                input_path=pre_caption_path,
                output_path=voiced_path,
                dub_audio_path=dub_wav,
                keep_background_audio=v_op.keep_background_audio,
                has_audio=has_audio,
            )
            has_audio = True

        if caption_ops:
            assert cached_segments is not None
            cap_op = caption_ops[-1]
            _report(48.0, "Generating captions")
            transcript_path = job_dir / "transcript.json"
            transcript_path.write_text(
                json.dumps([s.model_dump() for s in cached_segments], indent=2),
                encoding="utf-8",
            )
            artifacts.append(
                self._make_artifact(
                    kind="transcript",
                    path=transcript_path,
                    mime_type="application/json",
                    metadata={"segment_count": len(cached_segments)},
                )
            )

            srt_path = job_dir / "captions.srt"
            generate_srt(
                segments=cached_segments,
                output_srt_path=srt_path,
                max_words_per_cue=cap_op.max_words_per_cue or self.default_max_words_per_line,
                max_chars_per_cue=cap_op.max_chars_per_cue,
            )
            artifacts.append(
                self._make_artifact(
                    kind="subtitles_srt",
                    path=srt_path,
                    mime_type="application/x-subrip",
                    metadata={"segment_count": len(cached_segments)},
                )
            )

            master_path = job_dir / "master_edited.mp4"
            pre_probe = await self.runner.probe(voiced_path)
            pre_dur = float(pre_probe.get("duration_sec") or base_duration or 0.0)
            _report(50.0, "Burning captions")
            await self._burn_subtitles_only(
                input_path=voiced_path,
                output_path=master_path,
                srt_path=srt_path,
                has_audio=bool(pre_probe.get("has_audio", has_audio)),
                font_size=cap_op.font_size,
                margin_v=cap_op.margin_v,
                progress_cb=_sub_progress(50.0, 68.0, "Burning captions"),
                duration_sec=pre_dur or None,
            )
        else:
            master_path = voiced_path

        master_probe = await self.runner.probe(master_path)
        master_dur = float(master_probe.get("duration_sec") or base_duration or 0.0)

        # Step 3: Export requested output profile(s)
        targets: list[tuple[str, str, int, int]] = []
        if output_profile in (OutputProfile.LANDSCAPE_16X9, OutputProfile.BOTH):
            targets.append(("video_16x9", "landscape_16x9.mp4", 1920, 1080))
        if output_profile in (OutputProfile.VERTICAL_9X16, OutputProfile.BOTH):
            targets.append(("video_9x16", "vertical_9x16.mp4", 1080, 1920))

        rendition_probes: dict[str, Any] = {"master": master_probe, "renditions": {}}
        export_start = 68.0 if (pre_caption_ops or caption_ops or voice_ops) else 10.0
        export_end = 97.0
        step_span = (export_end - export_start) / max(1, len(targets))

        for idx, (kind, filename, w, h) in enumerate(targets):
            stage_label = f"Exporting {w}x{h}"
            s_pct = export_start + idx * step_span
            e_pct = s_pct + step_span
            _report(s_pct, stage_label)
            out_path = job_dir / filename
            await self._export_rendition(
                master_path,
                out_path,
                w,
                h,
                master_probe["has_audio"],
                progress_cb=_sub_progress(s_pct, e_pct, stage_label),
                duration_sec=master_dur or None,
            )
            probe_data = await self.runner.probe(out_path)
            rendition_probes["renditions"][kind] = probe_data
            artifacts.append(
                self._make_artifact(
                    kind=kind,  # type: ignore[arg-type]
                    path=out_path,
                    mime_type="video/mp4",
                    metadata={"width": w, "height": h, "probe": probe_data},
                )
            )

            # Generate a review thumbnail for each rendered format
            thumb_path = thumb_dir / f"{kind}_thumb.jpg"
            await self.generate_thumbnail(out_path, thumb_path, timestamp_sec=0.5)
            artifacts.append(
                self._make_artifact(
                    kind="thumbnail",
                    path=thumb_path,
                    mime_type="image/jpeg",
                    metadata={"for_rendition": kind, "width": w, "height": h},
                )
            )

        _report(98.0, "Writing metadata manifest")

        # Step 4: Write structured probe & manifest JSON artifacts
        probe_json_path = job_dir / "probe.json"
        probe_json_path.write_text(json.dumps(rendition_probes, indent=2), encoding="utf-8")
        artifacts.append(
            self._make_artifact(
                kind="probe",
                path=probe_json_path,
                mime_type="application/json",
                metadata={"renditions": list(rendition_probes["renditions"].keys())},
            )
        )

        manifest = {
            "job_id": job_id,
            "output_profile": output_profile.value,
            "source_ids": [s.source_id for s in sources],
            "operations": [op.model_dump() for op in operations],
            "artifacts": [a.model_dump() for a in artifacts],
        }
        manifest_path = job_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        artifacts.append(
            self._make_artifact(
                kind="manifest",
                path=manifest_path,
                mime_type="application/json",
                metadata={"artifact_count": len(artifacts) + 1},
            )
        )
        return artifacts

    async def generate_thumbnail(
        self, video_path: Path, output_path: Path, timestamp_sec: float = 0.5
    ) -> Path:
        """Extract a single JPEG preview frame at `timestamp_sec` (falls back to frame 0)."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        probe = await self.runner.probe(video_path)
        duration = probe.get("duration_sec") or 1.0
        ts = min(max(0.0, timestamp_sec), max(0.0, duration - 0.1))
        args = [
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
        await self.runner.run_ffmpeg(args)
        return output_path

    async def _concat_sources(self, sources: list[SourceAsset], output_path: Path) -> bool:
        """Normalize and concatenate multiple clips using the FFmpeg concat filter."""
        any_audio = any(bool(s.probe.get("has_audio", False)) for s in sources)
        inputs: list[str] = []
        filter_parts: list[str] = []
        concat_inputs: list[str] = []

        # Use first video's resolution or 1920x1080 as common concat canvas
        first_v = sources[0].probe.get("video") or {}
        target_w = int(first_v.get("width") or 1920)
        target_h = int(first_v.get("height") or 1080)

        for idx, src in enumerate(sources):
            inputs.extend(["-i", src.local_path])
            filter_parts.append(
                f"[{idx}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{idx}]"
            )
            if any_audio:
                if src.probe.get("has_audio"):
                    filter_parts.append(
                        f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{idx}]"
                    )
                else:
                    dur = float(src.probe.get("duration_sec") or 1.0)
                    filter_parts.append(
                        f"anullsrc=channel_layout=stereo:sample_rate=48000:d={dur:.3f}[a{idx}]"
                    )
                concat_inputs.append(f"[v{idx}][a{idx}]")
            else:
                concat_inputs.append(f"[v{idx}]")

        a_flag = 1 if any_audio else 0
        out_streams = "[vcat][acat]" if any_audio else "[vcat]"
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(sources)}:v=1:a={a_flag}{out_streams}"
        )

        args = [
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vcat]",
            *(["-map", "[acat]", "-c:a", "aac", "-b:a", "192k"] if any_audio else []),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        await self.runner.run_ffmpeg(args)
        return any_audio

    async def _apply_operations(
        self,
        input_path: Path,
        output_path: Path,
        operations: list[EditOperation],
        has_audio: bool,
        watermark_sources: dict[str, SourceAsset],
        progress_cb: Callable[[float], None] | None = None,
        duration_sec: float | None = None,
    ) -> None:
        """Compile EditOperation list into an FFmpeg filtergraph and render master_edited.mp4."""
        pre_trim: list[str] = []
        v_filters: list[str] = []
        a_filters: list[str] = []
        extra_inputs: list[str] = []
        overlay_ops: list[WatermarkOp] = []

        for op in operations:
            if isinstance(op, TrimOp):
                pre_trim = ["-ss", f"{op.start_sec:.3f}"]
                if op.end_sec is not None:
                    pre_trim.extend(["-to", f"{op.end_sec:.3f}"])
                elif op.duration_sec is not None:
                    pre_trim.extend(["-t", f"{op.duration_sec:.3f}"])
            elif isinstance(op, ScaleOp):
                v_filters.append(f"scale={op.width}:{op.height}:flags=lanczos,setsar=1")
            elif isinstance(op, ReframeOp):
                w, h = ASPECT_DIMENSIONS[op.aspect_ratio]
                if op.width and op.height:
                    w, h = op.width, op.height
                v_filters.append(_reframe_filter(w, h, op.mode))
            elif isinstance(op, AudioNormalizeOp):
                if has_audio:
                    a_filters.append(
                        f"loudnorm=I={op.target_i}:TP={op.target_tp}:LRA={op.target_lra}"
                    )
            elif isinstance(op, FadeOp):
                if op.fade_in_sec > 0:
                    v_filters.append(f"fade=t=in:st=0:d={op.fade_in_sec:.3f}")
                    if has_audio:
                        a_filters.append(f"afade=t=in:st=0:d={op.fade_in_sec:.3f}")
                if op.fade_out_sec > 0 and op.total_duration_sec:
                    start_out = max(0.0, op.total_duration_sec - op.fade_out_sec)
                    v_filters.append(
                        f"fade=t=out:st={start_out:.3f}:d={op.fade_out_sec:.3f}"
                    )
                    if has_audio:
                        a_filters.append(
                            f"afade=t=out:st={start_out:.3f}:d={op.fade_out_sec:.3f}"
                        )
            elif isinstance(op, SpeedOp):
                if abs(op.factor - 1.0) > 1e-3:
                    v_filters.append(f"setpts=PTS/{op.factor:.4f}")
                    if has_audio:
                        a_filters.extend(_atempo_chain(op.factor))
            elif isinstance(op, TextOverlayOp):
                y_expr = {
                    "top": "40",
                    "center": "(h-text_h)/2",
                    "bottom": "h-text_h-48",
                }[op.position]
                draw = (
                    f"drawtext=text='{_escape_drawtext(op.text)}':"
                    f"fontsize={op.font_size}:fontcolor={op.font_color}:"
                    f"x=(w-text_w)/2:y={y_expr}:box=1:boxcolor=black@0.45:boxborderw=10"
                )
                if op.start_sec is not None and op.end_sec is not None:
                    draw += f":enable='between(t,{op.start_sec:.3f},{op.end_sec:.3f})'"
                v_filters.append(draw)
            elif isinstance(op, BurnSubtitlesOp):
                sub_path = Path(op.subtitle_path)
                if not sub_path.is_file():
                    raise FileNotFoundError(f"Subtitle file not found: {sub_path}")
                style = _subtitle_force_style()
                v_filters.append(
                    f"subtitles=filename='{_escape_filter_path(sub_path)}':force_style='{style}'"
                )
            elif isinstance(op, WatermarkOp):
                if op.image_source_id not in watermark_sources:
                    raise ValueError(f"Watermark source not found: {op.image_source_id}")
                overlay_ops.append(op)

        # Build command
        args: list[str] = [*pre_trim, "-i", str(input_path)]
        for wm in overlay_ops:
            extra_inputs.extend(["-i", watermark_sources[wm.image_source_id].local_path])
        args.extend(extra_inputs)

        if overlay_ops:
            # Use filter_complex when watermark inputs are present
            fc_parts: list[str] = []
            cur_v = "0:v"
            if v_filters:
                fc_parts.append(f"[{cur_v}]{','.join(v_filters)}[vbase]")
                cur_v = "vbase"
            for idx, wm in enumerate(overlay_ops, start=1):
                pos_expr = {
                    "top-left": f"{wm.margin_px}:{wm.margin_px}",
                    "top-right": f"W-w-{wm.margin_px}:{wm.margin_px}",
                    "bottom-left": f"{wm.margin_px}:H-h-{wm.margin_px}",
                    "bottom-right": f"W-w-{wm.margin_px}:H-h-{wm.margin_px}",
                }[wm.position]
                fc_parts.append(f"[{idx}:v]scale={wm.scale_width}:-1[wm{idx}]")
                next_v = f"vout{idx}"
                fc_parts.append(f"[{cur_v}][wm{idx}]overlay={pos_expr}[{next_v}]")
                cur_v = next_v

            map_args = ["-map", f"[{cur_v}]"]
            if has_audio:
                if a_filters:
                    fc_parts.append(f"[0:a]{','.join(a_filters)}[aout]")
                    map_args.extend(["-map", "[aout]"])
                else:
                    map_args.extend(["-map", "0:a?"])

            args.extend(["-filter_complex", ";".join(fc_parts), *map_args])
        else:
            if v_filters:
                args.extend(["-vf", ",".join(v_filters)])
            if has_audio and a_filters:
                args.extend(["-af", ",".join(a_filters)])

        args.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                *(["-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]),
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        await self.runner.run_ffmpeg(args, progress_cb=progress_cb, duration_sec=duration_sec)

    async def _burn_subtitles_only(
        self,
        input_path: Path,
        output_path: Path,
        srt_path: Path,
        has_audio: bool,
        font_size: int = 20,
        margin_v: int = 55,
        progress_cb: Callable[[float], None] | None = None,
        duration_sec: float | None = None,
    ) -> None:
        if self.runner.has_filter("subtitles"):
            style = _subtitle_force_style(font_size=font_size, margin_v=margin_v)
            vf = f"subtitles=filename='{_escape_filter_path(srt_path)}':force_style='{style}'"
            args = [
                "-i",
                str(input_path),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                *(["-c:a", "copy"] if has_audio else ["-an"]),
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            await self.runner.run_ffmpeg(args, progress_cb=progress_cb, duration_sec=duration_sec)
            return

        await self._burn_srt_with_pillow_overlay(
            input_path=input_path,
            output_path=output_path,
            srt_path=srt_path,
            has_audio=has_audio,
            margin_v=margin_v,
            progress_cb=progress_cb,
            duration_sec=duration_sec,
        )

    async def _burn_srt_with_pillow_overlay(
        self,
        input_path: Path,
        output_path: Path,
        srt_path: Path,
        has_audio: bool,
        margin_v: int = 55,
        progress_cb: Callable[[float], None] | None = None,
        duration_sec: float | None = None,
    ) -> None:
        """Render SRT cues as transparent PNGs with Pillow and overlay via FFmpeg."""
        cues = _parse_srt_cues(srt_path.read_text(encoding="utf-8"))
        if not cues:
            shutil.copy2(input_path, output_path)
            return

        from PIL import Image, ImageDraw, ImageFont

        probe = await self.runner.probe(input_path)
        video_info = probe.get("video") or {}
        vid_h = int(video_info.get("height") or 1080)
        vid_w = int(video_info.get("width") or 1920)
        px_size = max(20, int(vid_h * 0.045))

        font: Any = None
        for font_candidate in (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ):
            if Path(font_candidate).is_file():
                try:
                    font = ImageFont.truetype(font_candidate, px_size)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()

        cue_dir = output_path.parent / "caption_pngs"
        cue_dir.mkdir(parents=True, exist_ok=True)
        cue_pngs: list[tuple[float, float, Path]] = []

        for idx, (start, end, text) in enumerate(cues):
            dummy = Image.new("RGBA", (10, 10))
            d_draw = ImageDraw.Draw(dummy)
            bbox = d_draw.textbbox((0, 0), text, font=font, stroke_width=2)
            tw = max(1, bbox[2] - bbox[0])
            th = max(1, bbox[3] - bbox[1])
            pad_x = max(16, px_size // 2)
            pad_y = max(10, px_size // 3)
            img_w = min(vid_w - 20, tw + pad_x * 2)
            img_h = th + pad_y * 2

            img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle(
                [(0, 0), (img_w - 1, img_h - 1)],
                radius=max(8, px_size // 3),
                fill=(0, 0, 0, 175),
            )
            tx = max(pad_x, (img_w - tw) // 2) - bbox[0]
            ty = pad_y - bbox[1]
            draw.text(
                (tx, ty),
                text,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=2,
                stroke_fill=(0, 0, 0, 255),
            )
            png_path = cue_dir / f"cue_{idx:04d}.png"
            img.save(png_path, format="PNG")
            cue_pngs.append((start, end, png_path))

        # Overlay cues in batches of 25 to keep FFmpeg filtergraph compact
        current_in = input_path
        batch_size = 25
        total_batches = max(1, (len(cue_pngs) + batch_size - 1) // batch_size)
        for batch_num, b_idx in enumerate(range(0, len(cue_pngs), batch_size)):
            batch = cue_pngs[b_idx : b_idx + batch_size]
            is_last = b_idx + batch_size >= len(cue_pngs)
            batch_out = output_path if is_last else (cue_dir / f"batch_{b_idx}.mp4")

            inputs = ["-i", str(current_in)]
            fc_parts: list[str] = []
            cur_v = "0:v"
            for i, (start, end, png_path) in enumerate(batch, start=1):
                inputs.extend(["-i", str(png_path)])
                next_v = f"v{i}"
                fc_parts.append(
                    f"[{cur_v}][{i}:v]overlay=(W-w)/2:H-h-{margin_v}:enable='between(t,{start:.3f},{end:.3f})'[{next_v}]"
                )
                cur_v = next_v

            args = [
                *inputs,
                "-filter_complex",
                ";".join(fc_parts),
                "-map",
                f"[{cur_v}]",
                *(["-map", "0:a?", "-c:a", "copy"] if has_audio else ["-an"]),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(batch_out),
            ]
            batch_cb = (
                (lambda f, bn=batch_num: progress_cb((bn + f) / total_batches))
                if progress_cb is not None
                else None
            )
            await self.runner.run_ffmpeg(args, progress_cb=batch_cb, duration_sec=duration_sec)
            current_in = batch_out

    async def _apply_voice_dub(
        self,
        input_path: Path,
        output_path: Path,
        dub_audio_path: Path,
        keep_background_audio: bool,
        has_audio: bool,
    ) -> None:
        """Replace original voice (or mix over ducked original audio) with cloned AI audio."""
        if keep_background_audio and has_audio:
            args = [
                "-i",
                str(input_path),
                "-i",
                str(dub_audio_path),
                "-filter_complex",
                "[0:a]volume=0.12[bg];[1:a]aresample=48000[fg];[bg][fg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        else:
            args = [
                "-i",
                str(input_path),
                "-i",
                str(dub_audio_path),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        await self.runner.run_ffmpeg(args)

    async def _export_rendition(
        self,
        master_path: Path,
        output_path: Path,
        width: int,
        height: int,
        has_audio: bool,
        progress_cb: Callable[[float], None] | None = None,
        duration_sec: float | None = None,
    ) -> None:
        vf = _reframe_filter(width, height, mode="crop")
        args = [
            "-i",
            str(master_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            *(["-c:a", "copy"] if has_audio else ["-an"]),
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        await self.runner.run_ffmpeg(args, progress_cb=progress_cb, duration_sec=duration_sec)

    @staticmethod
    def _make_artifact(
        kind: str, path: Path, mime_type: str, metadata: dict[str, Any]
    ) -> RenderedArtifact:
        return RenderedArtifact(
            artifact_id=f"art_{uuid.uuid4().hex[:12]}",
            kind=kind,  # type: ignore[arg-type]
            path=str(path),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
            mime_type=mime_type,
            metadata=metadata,
        )

