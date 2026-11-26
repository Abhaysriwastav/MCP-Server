"""Domain models for video editing, mixed sources, approval, and publishing."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp string."""
    return datetime.now(UTC).isoformat()


class SourceKind(StrEnum):
    LOCAL = "local"
    HTTP = "http"
    S3 = "s3"
    YOUTUBE = "youtube"


class TranscriptWord(BaseModel):
    """Word-level timestamp emitted by Whisper."""

    word: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    probability: float | None = None


class TranscriptSegment(BaseModel):
    """Segment-level transcript with optional word-level timestamps."""

    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)


class SourceAsset(BaseModel):
    """Registered media source resolved into the workspace."""

    source_id: str
    uri: str
    kind: SourceKind
    local_path: str
    sha256: str
    size_bytes: int
    filename: str
    probe: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


# ---------------------------------------------------------------------------
# Composable Editing Operations
# ---------------------------------------------------------------------------


class TrimOp(BaseModel):
    op: Literal["trim"] = "trim"
    start_sec: float = Field(default=0.0, ge=0.0)
    end_sec: float | None = Field(default=None, gt=0.0)
    duration_sec: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> TrimOp:
        if self.end_sec is not None and self.duration_sec is not None:
            raise ValueError("Specify either end_sec or duration_sec, not both.")
        if self.end_sec is not None and self.end_sec <= self.start_sec:
            raise ValueError("end_sec must be greater than start_sec.")
        return self


class ScaleOp(BaseModel):
    op: Literal["scale"] = "scale"
    width: int = Field(ge=16, le=7680)
    height: int = Field(ge=16, le=4320)


class ReframeOp(BaseModel):
    op: Literal["reframe"] = "reframe"
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:5"]
    mode: Literal["crop", "pad"] = "crop"
    width: int | None = Field(default=None, ge=16, le=7680)
    height: int | None = Field(default=None, ge=16, le=4320)


class AudioNormalizeOp(BaseModel):
    op: Literal["audio_normalize"] = "audio_normalize"
    target_i: float = Field(default=-14.0, ge=-36.0, le=-5.0)
    target_tp: float = Field(default=-1.5, ge=-9.0, le=0.0)
    target_lra: float = Field(default=11.0, ge=1.0, le=20.0)


class FadeOp(BaseModel):
    op: Literal["fade"] = "fade"
    fade_in_sec: float = Field(default=0.0, ge=0.0, le=30.0)
    fade_out_sec: float = Field(default=0.0, ge=0.0, le=30.0)
    total_duration_sec: float | None = Field(default=None, gt=0.0)


class SpeedOp(BaseModel):
    op: Literal["speed"] = "speed"
    factor: float = Field(default=1.0, ge=0.25, le=4.0)


class TextOverlayOp(BaseModel):
    op: Literal["text_overlay"] = "text_overlay"
    text: str = Field(min_length=1, max_length=200)
    position: Literal["top", "center", "bottom"] = "bottom"
    font_size: int = Field(default=36, ge=12, le=144)
    font_color: str = Field(default="white")
    start_sec: float | None = Field(default=None, ge=0.0)
    end_sec: float | None = Field(default=None, gt=0.0)


class WatermarkOp(BaseModel):
    op: Literal["watermark"] = "watermark"
    image_source_id: str
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-right"
    margin_px: int = Field(default=24, ge=0, le=200)
    scale_width: int = Field(default=160, ge=16, le=1000)


class BurnSubtitlesOp(BaseModel):
    op: Literal["burn_subtitles"] = "burn_subtitles"
    subtitle_path: str


class AutoCaptionOp(BaseModel):
    op: Literal["auto_caption"] = "auto_caption"
    max_words_per_cue: int | None = Field(default=None, ge=1, le=20)
    max_chars_per_cue: int = Field(default=38, ge=10, le=120)
    font_size: int = Field(default=20, ge=10, le=72)
    margin_v: int = Field(default=55, ge=0, le=240)


class VoiceCloneOp(BaseModel):
    op: Literal["voice_clone"] = "voice_clone"
    reference_audio_source_id: str | None = None
    voice_id: str | None = None
    script_text: str | None = None
    language: str = Field(default="en", min_length=2, max_length=10)
    target_language: str | None = Field(default=None, min_length=2, max_length=10)
    keep_background_audio: bool = False


class RemoveSilencesOp(BaseModel):
    op: Literal["remove_silences"] = "remove_silences"
    noise_db: float = Field(default=-32.0, ge=-60.0, le=-10.0)
    min_silence_sec: float = Field(default=0.6, ge=0.2, le=5.0)
    padding_sec: float = Field(default=0.1, ge=0.0, le=0.5)


class SmartCropOp(BaseModel):
    op: Literal["smart_crop"] = "smart_crop"
    enabled: bool = True


EditOperation = Annotated[
    Union[
        TrimOp,
        ScaleOp,
        ReframeOp,
        AudioNormalizeOp,
        FadeOp,
        SpeedOp,
        TextOverlayOp,
        WatermarkOp,
        BurnSubtitlesOp,
        AutoCaptionOp,
        VoiceCloneOp,
        RemoveSilencesOp,
        SmartCropOp,
    ],
    Field(discriminator="op"),
]


class OutputProfile(StrEnum):
    """Output format presets supporting both landscape & vertical + structured metadata."""

    LANDSCAPE_16X9 = "landscape_16x9"
    VERTICAL_9X16 = "vertical_9x16"
    BOTH = "both"


class RenderedArtifact(BaseModel):
    """A single rendered media file or metadata artifact produced by a job."""

    artifact_id: str
    kind: Literal[
        "video_16x9",
        "video_9x16",
        "video_custom",
        "thumbnail",
        "manifest",
        "probe",
        "subtitles_srt",
        "transcript",
        "voice_dub",
    ]
    path: str
    sha256: str
    size_bytes: int
    mime_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Job Lifecycle & Approval State Machine
# ---------------------------------------------------------------------------


class JobStatus(StrEnum):
    DRAFT = "draft"
    RENDERING = "rendering"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    READY_FOR_REVIEW = "ready_for_review"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    FAILED = "failed"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRecord(BaseModel):
    """Immutable audit record for human-in-the-loop publishing approval."""

    approval_id: str
    job_id: str
    decision: ApprovalDecision
    reviewer: str | None = None
    notes: str | None = None
    artifact_checksums: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    decided_at: str | None = None


class EditJob(BaseModel):
    """Persistent video editing job with source references, edit plan, outputs, and approval."""

    job_id: str
    title: str
    source_ids: list[str]
    operations: list[dict[str, Any]] = Field(default_factory=list)
    output_profile: OutputProfile = OutputProfile.BOTH
    status: JobStatus = JobStatus.DRAFT
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    progress_stage: str | None = None
    render_started_at: str | None = None
    eta_sec: float | None = None
    artifacts: list[RenderedArtifact] = Field(default_factory=list)
    approval_id: str | None = None
    publish_records: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

