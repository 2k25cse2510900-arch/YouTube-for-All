"""State Management and Atomic Manifest Persistence for Pipeline Orchestration."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Dict, List, Optional

from config.settings import get_settings
from src.common.logger import setup_logger
from src.pipeline.exceptions import ConcurrentPipelineExecutionError, PipelineRecoveryError
from src.pipeline.models import (
    PipelineProductionState,
    PipelineStage,
    PipelineStageRecord,
    StageStatus,
)

logger = setup_logger("pipeline_state_manager")


class PipelineStateManager:
    """Manages persistent state manifests, concurrency locks, and execution history."""

    def __init__(
        self,
        base_productions_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None,
    ):
        settings = get_settings()
        self.productions_dir = Path(base_productions_dir or settings.paths.productions_output_dir)
        self.state_dir = Path(state_dir or (settings.paths.data_dir / "processed" / "pipeline"))

        self.productions_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._active_locks: Dict[str, Path] = {}

    def _get_state_file_path(self, production_id: str, storyboard_id: Optional[str] = None) -> Path:
        """Find or compute the path to pipeline_state.json for a production."""
        if storyboard_id:
            direct = self.productions_dir / storyboard_id / production_id / "pipeline_state.json"
            if direct.exists():
                return direct

        # Search productions_dir
        if self.productions_dir.exists():
            for sb_dir in self.productions_dir.iterdir():
                if sb_dir.is_dir():
                    candidate = sb_dir / production_id / "pipeline_state.json"
                    if candidate.exists():
                        return candidate

        # Check central state_dir
        central = self.state_dir / f"{production_id}_state.json"
        if central.exists():
            return central

        if storyboard_id:
            return self.productions_dir / storyboard_id / production_id / "pipeline_state.json"
        return central

    def _find_package_manifest_path(self, production_id: str, storyboard_id: Optional[str] = None) -> Optional[Path]:
        """Locate package_manifest.json on disk for a production ID."""
        if storyboard_id:
            direct = self.productions_dir / storyboard_id / production_id / "package_manifest.json"
            if direct.exists():
                return direct

        if self.productions_dir.exists():
            for sb_dir in self.productions_dir.iterdir():
                if sb_dir.is_dir():
                    candidate = sb_dir / production_id / "package_manifest.json"
                    if candidate.exists():
                        return candidate
        return None

    def _reconstruct_state_from_package(self, pkg_manifest_path: Path) -> Optional[PipelineProductionState]:
        """Synthesize and persist a PipelineProductionState from an existing package_manifest.json."""
        try:
            with open(pkg_manifest_path, "r", encoding="utf-8") as f:
                pkg_data = json.load(f)

            prod_id = pkg_data.get("production_id")
            sb_id = pkg_data.get("storyboard_id")
            if not prod_id or not sb_id:
                return None

            # Resolve script_id from storyboard file if possible
            script_id = sb_id
            settings = get_settings()
            sb_file = settings.paths.processed_dir / "storyboards" / f"{sb_id}.json"
            if sb_file.exists():
                try:
                    with open(sb_file, "r", encoding="utf-8") as sbf:
                        sb_content = json.load(sbf)
                        script_id = sb_content.get("source_script_id") or sb_content.get("storyboard_id") or sb_id
                except Exception:
                    pass

            state = self.init_production_state(
                production_id=prod_id,
                script_id=script_id,
                storyboard_id=sb_id,
                upload_enabled=False,
            )

            # Record package creation stage
            state.update_stage_status(
                stage=PipelineStage.PACKAGE_CREATION,
                status=StageStatus.COMPLETED,
                output_assets={"root_dir": str(pkg_manifest_path.parent)},
                notes=f"Discovered and initialized from storage package at {pkg_manifest_path.parent}",
            )

            # Inspect assets present in package
            assets = pkg_data.get("assets", [])
            has_images = any(a.get("asset_type") == "scene_image" for a in assets)
            if has_images:
                unapproved = [a for a in assets if a.get("asset_type") == "scene_image" and a.get("metadata", {}).get("status") != "approved"]
                if unapproved:
                    state.current_stage = PipelineStage.IMAGE_VALIDATION
                    state.overall_status = StageStatus.BLOCKED
                    state.error_message = f"Visual assets pending human review: {len(unapproved)} scene(s)"
                    state.update_stage_status(PipelineStage.IMAGE_VALIDATION, StageStatus.BLOCKED, notes=state.error_message)
                else:
                    state.update_stage_status(PipelineStage.IMAGE_VALIDATION, StageStatus.COMPLETED, notes="All scene images approved")

            # Check if video already exists
            has_video = any(a.get("asset_type") == "final_video" for a in assets)
            if has_video:
                state.update_stage_status(PipelineStage.VIDEO_RENDERING, StageStatus.COMPLETED, notes="Rendered video present in package")

            self.save_state(state)
            logger.info("Successfully reconstructed pipeline state for '%s' from package manifest.", prod_id)
            return state
        except Exception as err:
            logger.error("Failed to reconstruct state from package '%s': %s", pkg_manifest_path, err)
            return None

    def _get_lock_file(self, production_id: str) -> Path:
        return self.state_dir / f"{production_id}.lock"

    def acquire_lock(self, production_id: str) -> None:
        """Acquire an execution lock for a production to prevent concurrent execution."""
        lock_file = self._get_lock_file(production_id)
        if lock_file.exists():
            # Check if stale lock (> 2 hours old)
            try:
                mtime = datetime.fromtimestamp(lock_file.stat().st_mtime, tz=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - mtime).total_seconds()
                if age_seconds < 7200:
                    raise ConcurrentPipelineExecutionError(
                        f"Production '{production_id}' is currently running in another process "
                        f"(Lock acquired {age_seconds:.0f}s ago at {lock_file}). "
                        "Concurrent execution for the same production is blocked to prevent asset corruption."
                    )
                logger.warning("Releasing stale lock for '%s' (Age: %.0fs)", production_id, age_seconds)
            except OSError:
                pass

        try:
            lock_file.write_text(f"pid={os.getpid()}\ntime={datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
            self._active_locks[production_id] = lock_file
        except Exception as err:
            raise ConcurrentPipelineExecutionError(f"Could not acquire lock for '{production_id}': {err}") from err

    def release_lock(self, production_id: str) -> None:
        """Release the execution lock."""
        lock_file = self._get_lock_file(production_id)
        if lock_file.exists():
            try:
                lock_file.unlink()
            except OSError as err:
                logger.warning("Failed to remove lock file '%s': %s", lock_file, err)
        self._active_locks.pop(production_id, None)

    def init_production_state(
        self,
        production_id: str,
        script_id: str,
        storyboard_id: str,
        upload_enabled: bool = False,
    ) -> PipelineProductionState:
        """Initialize and persist a new production state manifest."""
        state = PipelineProductionState(
            production_id=production_id,
            script_id=script_id,
            storyboard_id=storyboard_id,
            current_stage=PipelineStage.SCRIPT_SELECTION,
            overall_status=StageStatus.PENDING,
            stages={},
            upload_enabled=upload_enabled,
        )

        # Pre-populate all stages in PENDING state
        for stg in PipelineStage:
            state.stages[stg.value] = PipelineStageRecord(stage=stg, status=StageStatus.PENDING)

        self.save_state(state)
        logger.info("Initialized pipeline production state for '%s' (Script: %s, Storyboard: %s)", production_id, script_id, storyboard_id)
        return state

    def save_state(self, state: PipelineProductionState) -> None:
        """Atomically persist state manifest to disk."""
        target_file = self._get_state_file_path(state.production_id, state.storyboard_id)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        state.updated_at = datetime.now(timezone.utc)
        payload = state.model_dump_json(indent=2)

        # Atomic write: write to temp file then rename
        tmp_dir = target_file.parent
        with tempfile.NamedTemporaryFile("w", dir=str(tmp_dir), delete=False, encoding="utf-8") as tf:
            tf.write(payload)
            temp_name = tf.name

        os.replace(temp_name, target_file)

        # Also write copy into central state_dir for quick discovery
        central_file = self.state_dir / f"{state.production_id}_state.json"
        try:
            with tempfile.NamedTemporaryFile("w", dir=str(self.state_dir), delete=False, encoding="utf-8") as tf2:
                tf2.write(payload)
                t2_name = tf2.name
            os.replace(t2_name, central_file)
        except Exception:
            pass

    def get_state(self, production_id: str, storyboard_id: Optional[str] = None) -> Optional[PipelineProductionState]:
        """Load persistent production state from disk, or reconstruct from storage package if missing."""
        target_file = self._get_state_file_path(production_id, storyboard_id)
        if not target_file.exists():
            pkg_manifest = self._find_package_manifest_path(production_id, storyboard_id)
            if pkg_manifest:
                return self._reconstruct_state_from_package(pkg_manifest)
            return None

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PipelineProductionState(**data)
        except Exception as err:
            logger.error("Failed to parse pipeline state file '%s': %s", target_file, err)
            return None

    def record_stage_start(
        self,
        production_id: str,
        stage: PipelineStage,
        input_checksums: Optional[Dict[str, str]] = None,
        storyboard_id: Optional[str] = None,
    ) -> PipelineProductionState:
        """Record the start of a pipeline stage."""
        state = self.get_state(production_id, storyboard_id=storyboard_id)
        if not state:
            raise PipelineRecoveryError(f"Cannot record stage start: State for '{production_id}' not found.")

        rec = state.update_stage_status(stage, StageStatus.RUNNING)
        if input_checksums:
            rec.input_checksums.update(input_checksums)
        self.save_state(state)
        logger.info("[%s] Started stage '%s'.", production_id, stage.value)
        return state

    def record_stage_completed(
        self,
        production_id: str,
        stage: PipelineStage,
        output_assets: Optional[Dict[str, str]] = None,
        notes: Optional[str] = None,
        storyboard_id: Optional[str] = None,
    ) -> PipelineProductionState:
        """Record the successful completion of a pipeline stage."""
        state = self.get_state(production_id, storyboard_id=storyboard_id)
        if not state:
            raise PipelineRecoveryError(f"Cannot record stage completion: State for '{production_id}' not found.")

        state.update_stage_status(stage, StageStatus.COMPLETED, output_assets=output_assets, notes=notes)
        self.save_state(state)
        logger.info("[%s] Completed stage '%s'.", production_id, stage.value)
        return state

    def record_stage_failed(
        self,
        production_id: str,
        stage: PipelineStage,
        error_message: str,
        storyboard_id: Optional[str] = None,
    ) -> PipelineProductionState:
        """Record that a pipeline stage failed."""
        state = self.get_state(production_id, storyboard_id=storyboard_id)
        if not state:
            raise PipelineRecoveryError(f"Cannot record stage failure: State for '{production_id}' not found.")

        state.update_stage_status(stage, StageStatus.FAILED, error_message=error_message)
        self.save_state(state)
        logger.error("[%s] Failed at stage '%s': %s", production_id, stage.value, error_message)
        return state

    def record_stage_blocked(
        self,
        production_id: str,
        stage: PipelineStage,
        reason: str,
        storyboard_id: Optional[str] = None,
    ) -> PipelineProductionState:
        """Record that a pipeline stage was blocked by a safety gate."""
        state = self.get_state(production_id, storyboard_id=storyboard_id)
        if not state:
            raise PipelineRecoveryError(f"Cannot record stage blocked: State for '{production_id}' not found.")

        state.update_stage_status(stage, StageStatus.BLOCKED, error_message=reason)
        self.save_state(state)
        logger.warning("[%s] Stage '%s' BLOCKED: %s", production_id, stage.value, reason)
        return state

    def list_all_productions(self) -> List[PipelineProductionState]:
        """Discover and return all production states across the repository."""
        results: Dict[str, PipelineProductionState] = {}

        # Scan state_dir
        if self.state_dir.exists():
            for sf in self.state_dir.glob("*_state.json"):
                try:
                    with open(sf, "r", encoding="utf-8") as f:
                        st = PipelineProductionState(**json.load(f))
                        results[st.production_id] = st
                except Exception:
                    pass

        # Scan productions_dir
        if self.productions_dir.exists():
            for sb_dir in self.productions_dir.iterdir():
                if sb_dir.is_dir():
                    for prod_dir in sb_dir.iterdir():
                        if not prod_dir.is_dir():
                            continue
                        sf = prod_dir / "pipeline_state.json"
                        if sf.exists():
                            try:
                                with open(sf, "r", encoding="utf-8") as f:
                                    st = PipelineProductionState(**json.load(f))
                                    results[st.production_id] = st
                            except Exception:
                                pass
                        elif (prod_dir / "package_manifest.json").exists():
                            # Package exists on disk without pipeline_state.json; reconstruct
                            recovered = self.get_state(prod_dir.name, sb_dir.name)
                            if recovered:
                                results[recovered.production_id] = recovered

        return sorted(results.values(), key=lambda s: s.created_at, reverse=True)
