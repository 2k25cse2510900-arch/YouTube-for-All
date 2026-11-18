"""Recovery manager providing crash detection, checkpoint verification, and resumption logic."""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.common.logger import setup_logger
from src.pipeline.models import (
    PipelineProductionState,
    PipelineStage,
    PipelineStageRecord,
    StageStatus,
)
from src.pipeline.state_manager import PipelineStateManager

logger = setup_logger("pipeline_recovery")

STAGE_SEQUENCE: List[PipelineStage] = [
    PipelineStage.SCRIPT_SELECTION,
    PipelineStage.SCRIPT_VALIDATION,
    PipelineStage.RESEARCH_VERIFICATION,
    PipelineStage.STORYBOARD_VALIDATION,
    PipelineStage.PACKAGE_CREATION,
    PipelineStage.IMAGE_VALIDATION,
    PipelineStage.VOICE_SYNTHESIS,
    PipelineStage.CAPTION_GENERATION,
    PipelineStage.AUDIO_MIXING,
    PipelineStage.VIDEO_RENDERING,
    PipelineStage.QUALITY_CHECK,
    PipelineStage.HUMAN_REVIEW,
    PipelineStage.UPLOAD_PREPARATION,
]


class PipelineRecoveryManager:
    """Inspects interrupted productions, verifies existing assets, and calculates safe resumption checkpoints."""

    def __init__(self, state_manager: Optional[PipelineStateManager] = None):
        self.state_manager = state_manager or PipelineStateManager()

    @classmethod
    def compute_file_hash(cls, path: Path) -> str:
        """Calculate SHA-256 hash of a file."""
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def verify_stage_output_assets(self, stage_record: PipelineStageRecord) -> Tuple[bool, List[str]]:
        """Verify that all recorded output assets for a stage exist on disk and are non-empty.

        Returns:
            Tuple[is_intact, missing_or_corrupt_files]
        """
        if not stage_record.output_assets:
            return True, []

        missing_or_corrupt: List[str] = []
        for name, file_path in stage_record.output_assets.items():
            p = Path(file_path).resolve()
            if not p.exists():
                missing_or_corrupt.append(f"{name} (missing: {file_path})")
            elif p.stat().st_size == 0:
                missing_or_corrupt.append(f"{name} (zero bytes: {file_path})")

        return len(missing_or_corrupt) == 0, missing_or_corrupt

    def evaluate_resumption_plan(self, state: PipelineProductionState) -> Dict[str, Any]:
        """Examine production state in sequence and identify the exact stage to resume from.

        Guarantees:
        - Completed stages with verified files are preserved and never repeated.
        - Stages with missing/corrupted output files are invalidated.
        - Preserves all intact local assets.
        """
        last_intact_stage: Optional[PipelineStage] = None
        next_resume_stage: Optional[PipelineStage] = None
        verified_assets: Dict[str, str] = {}
        invalidated_stages: List[str] = []

        for stage in STAGE_SEQUENCE:
            rec = state.stages.get(stage.value)
            if not rec or rec.status != StageStatus.COMPLETED:
                # First non-completed stage is our resume target
                if next_resume_stage is None:
                    next_resume_stage = stage
                continue

            # Verify files on disk
            is_intact, defects = self.verify_stage_output_assets(rec)
            if is_intact:
                last_intact_stage = stage
                verified_assets.update(rec.output_assets)
            else:
                logger.warning(
                    "Stage '%s' was recorded COMPLETED but assets are missing or corrupted: %s. Invalidating checkpoint.",
                    stage.value, defects
                )
                rec.status = StageStatus.FAILED
                rec.error_message = f"Recovery detected missing output files: {defects}"
                invalidated_stages.append(stage.value)
                if next_resume_stage is None:
                    next_resume_stage = stage

        if next_resume_stage is None:
            # All pipeline stages through upload preparation were completed
            next_resume_stage = PipelineStage.UPLOAD_PREPARATION

        can_resume = True
        plan = {
            "production_id": state.production_id,
            "script_id": state.script_id,
            "storyboard_id": state.storyboard_id,
            "current_recorded_stage": state.current_stage.value,
            "last_intact_stage": last_intact_stage.value if last_intact_stage else None,
            "resume_stage": next_resume_stage.value,
            "verified_assets_count": len(verified_assets),
            "verified_assets": verified_assets,
            "invalidated_stages": invalidated_stages,
            "can_resume": can_resume,
        }

        logger.info(
            "Recovery plan for '%s': Resume from '%s' (Last intact: %s, Verified assets: %d)",
            state.production_id,
            next_resume_stage.value,
            last_intact_stage.value if last_intact_stage else "None",
            len(verified_assets),
        )
        return plan

    def calculate_recovery_plan(
        self,
        production_id_or_state: Any,
        storyboard: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Convenience method to calculate recovery plan from production ID or state."""
        if isinstance(production_id_or_state, str):
            sb_id = storyboard.storyboard_id if storyboard else None
            state = self.state_manager.get_state(production_id_or_state, storyboard_id=sb_id)
            if not state:
                from src.pipeline.exceptions import PipelineRecoveryError
                raise PipelineRecoveryError(f"Cannot calculate recovery plan: state for '{production_id_or_state}' not found.")
        else:
            state = production_id_or_state
        return self.evaluate_resumption_plan(state)

    def recover_production(self, production_id: str, storyboard_id: Optional[str] = None) -> Tuple[PipelineProductionState, Dict[str, Any]]:
        """Recover an interrupted or failed production, resetting failed in-flight stages safely."""
        state = self.state_manager.get_state(production_id, storyboard_id=storyboard_id)
        if not state:
            raise PipelineRecoveryError(f"Cannot recover production '{production_id}': State file not found.")

        plan = self.evaluate_resumption_plan(state)

        # Reset any stage currently stuck in RUNNING to PENDING or FAILED
        for s_val, rec in state.stages.items():
            if rec.status == StageStatus.RUNNING:
                rec.status = StageStatus.PENDING
                rec.error_message = "Reset from RUNNING state during crash recovery."

        state.is_recovered = True
        state.current_stage = PipelineStage(plan["resume_stage"])
        state.overall_status = StageStatus.PENDING
        self.state_manager.save_state(state)

        logger.info("Production '%s' recovered successfully. Ready to resume at '%s'.", production_id, state.current_stage.value)
        return state, plan
