"""Data models, state tracking schemas, and configuration for Pipeline Orchestration."""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.youtube_uploader.models import PrivacyStatus


class PipelineStage(str, Enum):
    """Sequential stages of YouTube Shorts automated production pipeline."""

    SCRIPT_SELECTION = "script_selection"
    SCRIPT_VALIDATION = "script_validation"
    RESEARCH_VERIFICATION = "research_verification"
    STORYBOARD_VALIDATION = "storyboard_validation"
    PACKAGE_CREATION = "package_creation"
    IMAGE_VALIDATION = "image_validation"
    VOICE_SYNTHESIS = "voice_synthesis"
    CAPTION_GENERATION = "caption_generation"
    AUDIO_MIXING = "audio_mixing"
    VIDEO_RENDERING = "video_rendering"
    QUALITY_CHECK = "quality_check"
    HUMAN_REVIEW = "human_review"
    UPLOAD_PREPARATION = "upload_preparation"
    YOUTUBE_UPLOAD = "youtube_upload"
    STORAGE_CLEANUP = "storage_cleanup"


class StageStatus(str, Enum):
    """Lifecycle execution states of pipeline stages."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"
    SKIPPED = "skipped"


class PipelineStageRecord(BaseModel):
    """Audit record capturing the execution state and outputs of an individual pipeline stage."""

    stage: PipelineStage
    status: StageStatus = Field(default=StageStatus.PENDING)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    input_checksums: Dict[str, str] = Field(
        default_factory=dict,
        description="SHA-256 hashes of input files to verify integrity on resumption.",
    )
    output_assets: Dict[str, str] = Field(
        default_factory=dict,
        description="Named mapping of generated output files (e.g. {'voiceover': '/path/to/voice.mp3'}).",
    )
    error_message: Optional[str] = None
    notes: Optional[str] = None

    def mark_running(self) -> None:
        self.status = StageStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self.error_message = None

    def mark_completed(self, output_assets: Optional[Dict[str, str]] = None, notes: Optional[str] = None) -> None:
        self.status = StageStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        if output_assets:
            self.output_assets.update(output_assets)
        if notes:
            self.notes = notes
        self.error_message = None

    def mark_failed(self, error_message: str) -> None:
        self.status = StageStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message

    def mark_blocked(self, reason: str) -> None:
        self.status = StageStatus.BLOCKED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = reason


class PipelineProductionState(BaseModel):
    """Persistent state manifest for an end-to-end Short production run."""

    production_id: str = Field(..., min_length=1)
    script_id: str = Field(..., min_length=1)
    storyboard_id: str = Field(..., min_length=1)
    current_stage: PipelineStage = Field(default=PipelineStage.SCRIPT_SELECTION)
    overall_status: StageStatus = Field(default=StageStatus.PENDING)
    stages: Dict[str, PipelineStageRecord] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    is_recovered: bool = Field(default=False, description="True if state was recovered after an interruption")
    human_approval_id: Optional[str] = None
    quality_report_status: Optional[str] = None
    upload_enabled: bool = Field(default=False, description="Upload switch; strictly False in Stage 7D")

    def get_stage_record(self, stage: PipelineStage) -> PipelineStageRecord:
        key = stage.value
        if key not in self.stages:
            self.stages[key] = PipelineStageRecord(stage=stage, status=StageStatus.PENDING)
        return self.stages[key]

    def update_stage_status(
        self,
        stage: PipelineStage,
        status: StageStatus,
        output_assets: Optional[Dict[str, str]] = None,
        error_message: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> PipelineStageRecord:
        rec = self.get_stage_record(stage)
        rec.status = status
        self.current_stage = stage
        self.updated_at = datetime.now(timezone.utc)

        if status == StageStatus.RUNNING:
            rec.mark_running()
            self.overall_status = StageStatus.RUNNING
        elif status == StageStatus.COMPLETED:
            rec.mark_completed(output_assets=output_assets, notes=notes)
        elif status == StageStatus.FAILED:
            rec.mark_failed(error_message or "Stage failed")
            self.overall_status = StageStatus.FAILED
            self.error_message = error_message
        elif status == StageStatus.BLOCKED:
            rec.mark_blocked(error_message or "Stage blocked by safety gate")
            self.overall_status = StageStatus.BLOCKED
            self.error_message = error_message

        return rec

    def is_stage_completed(self, stage: PipelineStage) -> bool:
        rec = self.stages.get(stage.value)
        return rec is not None and rec.status == StageStatus.COMPLETED


class PipelineConfig(BaseModel):
    """Runtime configuration options for pipeline execution."""

    upload_enabled: bool = Field(
        default=False,
        description="MANDATORY SAFETY SWITCH: Must default to False to prevent unintentional YouTube uploads.",
    )
    require_human_approval: bool = Field(
        default=True,
        description="Mandates human approval at Script, Image, and Upload gates.",
    )
    allow_synthetic_audio: bool = Field(
        default=False,
        description="Strictly False in production. True only in offline technical unit tests.",
    )
    allow_no_captions: bool = Field(
        default=False,
        description="If True, permits caption omission with an acknowledged QA warning.",
    )
    auto_approve_images: bool = Field(
        default=False,
        description="If True, auto-approves imported non-mock production images.",
    )
    default_privacy: PrivacyStatus = Field(
        default=PrivacyStatus.PRIVATE,
        description="Default upload privacy; always PRIVATE unless explicitly overridden.",
    )
    require_bgm: bool = Field(
        default=True,
        description="Requires licensed background music track for production video.",
    )
    require_sfx: bool = Field(
        default=False,
        description="Requires sound effect cues; optional by default.",
    )
    voice_id: Optional[str] = None
    video_preset: Optional[str] = None


class SceneImageInspectionReport(BaseModel):
    """Diagnostic report identifying visual asset readiness for all storyboard scenes."""

    storyboard_id: str
    total_scenes: int
    scene_statuses: Dict[int, str] = Field(default_factory=dict)
    missing_scenes: List[int] = Field(default_factory=list)
    unapproved_scenes: List[int] = Field(default_factory=list)
    mock_scenes: List[int] = Field(default_factory=list)
    is_ready_for_video: bool = False
    details: str = ""
