"""Composable FFmpeg video editing & dual-rendition export pipeline."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from video_mcp.media.ffmpeg_runner import FFmpegRunner, sha256_file
from video_mcp.models import (
    AudioNormalizeOp,
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
    TrimOp,
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
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


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

    def __init__(self, runner: FFmpegRunner, workspace_dir: Path) -> None:
        self.runner = runner
        self.workspace_dir = workspace_dir

    async def render_job(
        self,
        job_id: str,
        sources: list[SourceAsset],
        operations: list[EditOperation],
        output_profile: OutputProfile,
        watermark_sources: dict[str, SourceAsset] | None = None,
    ) -> list[RenderedArtifact]:
        """Run the full editing pipeline for a job and return rendered media + metadata artifacts."""
        if not sources:
            raise ValueError("At least one source asset is required to render a job.")

        job_dir = self.workspace_dir / "renders" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir = self.workspace_dir / "thumbnails" / job_id
        thumb_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Prepare base input (single clip or concatenated multi-clip)
        if len(sources) == 1:
            base_input = Path(sources[0].local_path)
            has_audio = bool(sources[0].probe.get("has_audio", False))
        else:
            base_input = job_dir / "concat_base.mp4"
            has_audio = await self._concat_sources(sources, base_input)

        # Step 2: Apply composable editing operations into an edited master (skip re-encode if no ops)
        if operations:
            master_path = job_dir / "master_edited.mp4"
            await self._apply_operations(
                input_path=base_input,
                output_path=master_path,
                operations=operations,
                has_audio=has_audio,
                watermark_sources=watermark_sources or {},
            )
        else:
            master_path = base_input

        master_probe = await self.runner.probe(master_path)
        artifacts: list[RenderedArtifact] = []

        # Step 3: Export requested output profile(s)
        targets: list[tuple[str, str, int, int]] = []
        if output_profile in (OutputProfile.LANDSCAPE_16X9, OutputProfile.BOTH):
            targets.append(("video_16x9", "landscape_16x9.mp4", 1920, 1080))
        if output_profile in (OutputProfile.VERTICAL_9X16, OutputProfile.BOTH):
            targets.append(("video_9x16", "vertical_9x16.mp4", 1080, 1920))

        rendition_probes: dict[str, Any] = {"master": master_probe, "renditions": {}}

        for kind, filename, w, h in targets:
            out_path = job_dir / filename
            await self._export_rendition(master_path, out_path, w, h, master_probe["has_audio"])
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
                v_filters.append(f"subtitles='{_escape_filter_path(sub_path)}'")
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
        await self.runner.run_ffmpeg(args)

    async def _export_rendition(
        self, master_path: Path, output_path: Path, width: int, height: int, has_audio: bool
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
        await self.runner.run_ffmpeg(args)

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

