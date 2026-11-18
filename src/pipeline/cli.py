"""Command-line interface for Pipeline Orchestration."""

import argparse
import json
from pathlib import Path
import sys
from typing import List, Optional

from config.settings import get_settings
from src.common.logger import setup_logger
from src.pipeline.models import PipelineConfig
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.recovery import PipelineRecoveryManager
from src.pipeline.reporter import PipelineReporter
from src.pipeline.state_manager import PipelineStateManager
from src.storage_manager.service import StorageManager

logger = setup_logger("pipeline_cli")


def handle_status(args: argparse.Namespace) -> int:
    """Handle 'pipeline status [production_id]' command."""
    state_mgr = PipelineStateManager()
    prod_id = getattr(args, "production_id", None)

    if prod_id:
        state = state_mgr.get_state(prod_id)
        if not state:
            print(f"Error: Production '{prod_id}' not found.")
            return 1
        if getattr(args, "json", False):
            print(state.model_dump_json(indent=2))
        else:
            print(PipelineReporter.format_production_status(state))
        return 0

    # No specific production ID: show latest or list overview
    all_prods = state_mgr.list_all_productions()
    if not all_prods:
        print("No pipeline productions found.")
        return 0

    latest = all_prods[0]
    if getattr(args, "json", False):
        print(latest.model_dump_json(indent=2))
    else:
        print(PipelineReporter.format_production_status(latest))
    return 0


def handle_list(args: argparse.Namespace) -> int:
    """Handle 'pipeline list' command."""
    state_mgr = PipelineStateManager()
    prods = state_mgr.list_all_productions()

    if getattr(args, "json", False):
        print(json.dumps([p.model_dump() for p in prods], indent=2, default=str))
        return 0

    if not prods:
        print("No pipeline productions found in repository.")
        return 0

    print(f"Total Productions: {len(prods)}")
    print("-" * 88)
    print(f"{'Production ID':<30} {'Script ID':<15} {'Current Stage':<22} {'Status':<10} {'Updated':<10}")
    print("-" * 88)
    for p in prods:
        up_str = p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else "-"
        print(f"{p.production_id:<30} {p.script_id:<15} {p.current_stage.value:<22} {p.overall_status.value.upper():<10} {up_str:<10}")
    print("-" * 88)
    return 0


def handle_prepare(args: argparse.Namespace) -> int:
    """Handle 'pipeline prepare --script-id SCRIPT_ID' command."""
    script_id = args.script_id
    print(f"Preparing production package for script '{script_id}'...")

    orchestrator = PipelineOrchestrator()
    try:
        # 1. Select & validate script
        script = orchestrator.select_and_validate_script(script_id=script_id)
        print(f"  [PASS] Script verified: '{script.title}' (ID: {script.script_id})")

        # 2. Find storyboard
        storage_mgr = StorageManager()
        storyboards = storage_mgr.find_storyboards_for_script(script.script_id)
        if not storyboards:
            print(f"Error: No storyboard dossier found for script '{script.script_id}'.")
            return 1
        storyboard = storyboards[0]
        print(f"  [PASS] Storyboard located: '{storyboard.storyboard_id}' ({len(storyboard.scenes)} scenes)")

        # 3. Verify research & validate storyboard
        orchestrator.verify_research(storyboard, script)
        print("  [PASS] Research verification: Scientific claims verified.")
        orchestrator.validate_storyboard(storyboard)
        print("  [PASS] Storyboard schema & constraints validated.")

        # 4. Initialize package
        pkg, state = orchestrator.initialize_production_package(storyboard, script)
        print(f"  [PASS] Production package initialized: '{pkg.production_id}' at {pkg.package_dir}")

        # 5. Prepare image prompts/manifest
        img_manifest = orchestrator.prepare_and_validate_images(storyboard, pkg)
        print(f"  [PASS] Image manifest prepared. Ready for manual/service import: {len(img_manifest.images)} scenes.")

        print("\nProduction preparation complete.")
        print(f"Production ID: {pkg.production_id}")
        print(f"Directory:     {pkg.package_dir}")
        return 0

    except Exception as exc:
        logger.exception("Production preparation failed: %s", exc)
        print(f"\n[FAIL] Preparation blocked: {exc}")
        return 1


def handle_validate(args: argparse.Namespace) -> int:
    """Handle 'pipeline validate --production-id PRODUCTION_ID' command."""
    prod_id = args.production_id
    state_mgr = PipelineStateManager()
    state = state_mgr.get_state(prod_id)
    if not state:
        print(f"Error: Production '{prod_id}' not found.")
        return 1

    storage_mgr = StorageManager()
    pkg = storage_mgr.load_production_package(prod_id)
    if not pkg:
        print(f"Error: Production package on disk for '{prod_id}' not found.")
        return 1

    storyboard = storage_mgr.load_storyboard_dossier(state.storyboard_id)
    if not storyboard:
        print(f"Error: Storyboard '{state.storyboard_id}' not found.")
        return 1

    print(f"Validating Production: {prod_id}")
    print("=" * 60)

    # 1. Image Inspection
    orchestrator = PipelineOrchestrator()
    manifest = orchestrator.image_engine.get_manifest(storyboard.storyboard_id)
    from src.pipeline.validators import PipelineGatekeeper
    inspection = PipelineGatekeeper.inspect_images(storyboard, manifest=manifest)
    print(PipelineReporter.format_scene_images_report(inspection))
    print()

    # 2. Overall Status
    print(PipelineReporter.format_production_status(state))
    return 0


def handle_render(args: argparse.Namespace) -> int:
    """Handle 'pipeline render --production-id PRODUCTION_ID' command."""
    prod_id = args.production_id
    orchestrator = PipelineOrchestrator()
    state_mgr = orchestrator.state_manager
    state = state_mgr.get_state(prod_id)
    if not state:
        print(f"Error: Production '{prod_id}' not found.")
        return 1

    storage_mgr = orchestrator.storage_manager
    pkg = storage_mgr.load_production_package(prod_id)
    if not pkg:
        print(f"Error: Production package on disk for '{prod_id}' not found.")
        return 1

    storyboard = storage_mgr.load_storyboard_dossier(state.storyboard_id)
    if not storyboard:
        print(f"Error: Storyboard '{state.storyboard_id}' not found.")
        return 1

    script = orchestrator.select_and_validate_script(script_id=state.script_id)
    manifest = orchestrator.image_engine.get_manifest(storyboard.storyboard_id)

    from src.pipeline.validators import PipelineGatekeeper
    from src.audio_engine.models import VoiceSynthesisResult

    # Verify Gate C
    try:
        PipelineGatekeeper.validate_gate_c_images(storyboard, manifest=manifest)
    except Exception as exc:
        print(f"\n[FAIL] Image validation (Gate C) blocked: {exc}")
        return 1

    # Verify Gate D audio assets
    voice_out = Path(pkg.root_dir) / "audio" / "voiceover.mp3"
    if not voice_out.exists():
        print(f"\n[FAIL] Voiceover audio missing at: {voice_out}. Synthesize voiceover first.")
        return 1

    voice_result = VoiceSynthesisResult(
        audio_path=str(voice_out),
        duration_seconds=storyboard.target_duration_seconds,
        voice_id=orchestrator.settings.audio.default_voice,
        provider="edge_tts",
        boundaries=[],
        is_mock_asset=False,
    )

    ass_path = Path(pkg.root_dir) / "captions" / "captions.ass"
    if not ass_path.exists():
        ass_path = None

    mixed_audio_file = Path(pkg.root_dir) / "audio" / "mixed_audio.wav"
    mixed_audio = None
    if mixed_audio_file.exists():
        from src.audio_engine.models import AudioMixResult
        mixed_audio = AudioMixResult(
            mixed_audio_path=str(mixed_audio_file),
            duration_seconds=voice_result.duration_seconds,
            voiceover_duration=voice_result.duration_seconds,
            is_synthetic_mix=False,
            sfx_count=0,
        )

    print(f"Rendering Video for Production: {prod_id}...")
    try:
        render_result = orchestrator.render_video(
            storyboard=storyboard,
            manifest=manifest,
            script=script,
            voice_result=voice_result,
            package=pkg,
            mixed_audio=mixed_audio,
            ass_caption_path=ass_path,
        )
        print(f"\n[PASS] Video render complete: {render_result.output_path}")
        print(f"Duration: {render_result.duration_seconds:.2f}s | Resolution: {render_result.width}x{render_result.height}")
        return 0
    except Exception as exc:
        logger.exception("Rendering failed: %s", exc)
        print(f"\n[FAIL] Video rendering blocked: {exc}")
        return 1


def handle_report(args: argparse.Namespace) -> int:
    """Handle 'pipeline report --production-id PRODUCTION_ID' command."""
    prod_id = args.production_id
    state_mgr = PipelineStateManager()
    state = state_mgr.get_state(prod_id)
    if not state:
        print(f"Error: Production '{prod_id}' not found.")
        return 1

    print(PipelineReporter.format_production_status(state))
    print()

    # Recovery diagnostic
    recovery_mgr = PipelineRecoveryManager(state_manager=state_mgr)
    try:
        plan = recovery_mgr.calculate_recovery_plan(prod_id)
        print(PipelineReporter.format_recovery_report(plan))
    except Exception:
        pass

    return 0


def handle_resume(args: argparse.Namespace) -> int:
    """Handle 'pipeline resume --production-id PRODUCTION_ID' command."""
    prod_id = args.production_id
    print(f"Resuming Production '{prod_id}'...")
    orchestrator = PipelineOrchestrator()
    try:
        state = orchestrator.state_manager.get_state(prod_id)
        if not state:
            print(f"Error: Production '{prod_id}' not found.")
            return 1
        storyboard = orchestrator.storage_manager.load_storyboard_dossier(state.storyboard_id)
        script = orchestrator.select_and_validate_script(script_id=state.script_id)
        final_state = orchestrator.resume_production(
            production_id=prod_id,
            storyboard=storyboard,
            script=script,
            human_approval_confirmed=getattr(args, "confirm_approval", False),
            approver_notes=getattr(args, "notes", None),
            accept_warnings=getattr(args, "accept_warnings", False),
        )
        print("\nProduction resumption complete.")
        print(PipelineReporter.format_production_status(final_state))
        return 0
    except Exception as exc:
        logger.exception("Resume failed: %s", exc)
        print(f"\n[FAIL] Resumption failed: {exc}")
        return 1


def handle_approve(args: argparse.Namespace) -> int:
    """Handle 'pipeline approve -p PRODUCTION_ID --notes NOTES' command."""
    prod_id = args.production_id
    notes = getattr(args, "notes", None)
    accept_warnings = getattr(args, "accept_warnings", False)

    if not notes or not notes.strip():
        print("Error: Human approver notes are mandatory (--notes 'Your review comments').")
        return 1

    from pathlib import Path
    from src.storage_manager.models import ProductionAssetType
    from src.quality_checker.models import QualityReport

    orchestrator = PipelineOrchestrator()
    state_mgr = orchestrator.state_manager
    state = state_mgr.get_state(prod_id)
    if not state:
        print(f"Error: Production '{prod_id}' not found.")
        return 1

    storage_mgr = orchestrator.storage_manager
    pkg = storage_mgr.load_production_package(prod_id)
    if not pkg:
        print(f"Error: Production package on disk for '{prod_id}' not found.")
        return 1

    storyboard = storage_mgr.load_storyboard_dossier(state.storyboard_id)
    script = orchestrator.select_and_validate_script(script_id=state.script_id)

    video_assets = [a for a in pkg.assets if a.asset_type == ProductionAssetType.FINAL_VIDEO]
    if not video_assets:
        print(f"Error: No final video asset found in package '{prod_id}'. Video must be rendered first.")
        return 1
    video_path = Path(video_assets[0].file_path)

    report_file = Path(pkg.root_dir) / "quality_report.json"
    if not report_file.exists():
        print(f"Error: Quality report not found at {report_file}. Run QA checks before approval.")
        return 1

    with open(report_file, "r", encoding="utf-8") as f:
        rep_data = json.load(f)
    quality_report = QualityReport.model_validate(rep_data)

    print(f"\nExplicit Human Approval for Production: {prod_id}")
    print(f"Script:     {script.title} ({script.id})")
    print(f"Storyboard: {storyboard.storyboard_id if storyboard else 'N/A'}")
    print(f"Video File: {video_path.name} ({video_path.stat().st_size} bytes)")
    print(f"QA Status:  {quality_report.overall_status.value}")
    print(f"Notes:      {notes}")

    try:
        approval = orchestrator.create_human_approval(
            package=pkg,
            video_path=video_path,
            script=script,
            quality_report=quality_report,
            approver_notes=notes,
            accept_warnings=accept_warnings,
            storyboard=storyboard,
        )
        print(f"\n[PASS] Human approval issued and signed: {pkg.root_dir / 'upload_approval.json'}")

        staging = orchestrator.prepare_upload_package(
            package=pkg,
            approval=approval,
            script=script,
            video_path=video_path,
            storyboard=storyboard,
        )
        print(f"[PASS] Upload package staged safely (Upload Enabled: {staging.upload_enabled}): {staging.status}")
        return 0
    except Exception as exc:
        logger.exception("Approval failed: %s", exc)
        print(f"\n[FAIL] Approval rejected: {exc}")
        return 1


def build_pipeline_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register pipeline subcommands under an existing parser or subparser group."""
    pipe_parser = subparsers.add_parser("pipeline", help="End-to-end Shorts production pipeline commands")
    cmd_sub = pipe_parser.add_subparsers(dest="pipeline_command", help="Pipeline subcommands")

    # status
    p_status = cmd_sub.add_parser("status", help="Show status table for production(s)")
    p_status.add_argument("production_id", nargs="?", default=None, help="Optional production ID")
    p_status.add_argument("--json", action="store_true", help="Output state as JSON")
    p_status.set_defaults(func=handle_status)

    # list
    p_list = cmd_sub.add_parser("list", help="List all productions and statuses")
    p_list.add_argument("--json", action="store_true", help="Output list as JSON")
    p_list.set_defaults(func=handle_list)

    # prepare
    p_prep = cmd_sub.add_parser("prepare", help="Prepare production package from approved script")
    p_prep.add_argument("-s", "--script-id", required=True, help="Approved script ID")
    p_prep.set_defaults(func=handle_prepare)

    # validate
    p_val = cmd_sub.add_parser("validate", help="Run Gate inspections on production assets")
    p_val.add_argument("-p", "--production-id", required=True, help="Production ID to validate")
    p_val.set_defaults(func=handle_validate)

    # render
    p_ren = cmd_sub.add_parser("render", help="Trigger video rendering for prepared package")
    p_ren.add_argument("-p", "--production-id", required=True, help="Production ID to render")
    p_ren.set_defaults(func=handle_render)

    # report
    p_rep = cmd_sub.add_parser("report", help="Output detailed quality and production report")
    p_rep.add_argument("-p", "--production-id", required=True, help="Production ID")
    p_rep.set_defaults(func=handle_report)

    # resume
    p_res = cmd_sub.add_parser("resume", help="Resume interrupted production from last valid checkpoint")
    p_res.add_argument("-p", "--production-id", required=True, help="Production ID to resume")
    p_res.add_argument("--confirm-approval", action="store_true", help="Confirm explicit human review sign-off")
    p_res.add_argument("-n", "--notes", default=None, help="Human reviewer notes when confirming approval")
    p_res.add_argument("--accept-warnings", action="store_true", help="Explicitly accept quality warnings")
    p_res.set_defaults(func=handle_resume)

    # approve
    p_app = cmd_sub.add_parser("approve", help="Explicit human approval for verified production package")
    p_app.add_argument("-p", "--production-id", required=True, help="Production ID to approve")
    p_app.add_argument("-n", "--notes", required=True, help="Mandatory reviewer sign-off notes")
    p_app.add_argument("--accept-warnings", action="store_true", help="Explicitly accept quality warnings")
    p_app.set_defaults(func=handle_approve)

    return pipe_parser


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point when invoked as python -m src.pipeline.cli."""
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="A Lesson With AI - Pipeline Orchestrator CLI",
    )
    sub = parser.add_subparsers(dest="pipeline_command", help="Pipeline subcommands")

    # Add commands directly for standalone execution
    p_status = sub.add_parser("status", help="Show status table for production(s)")
    p_status.add_argument("production_id", nargs="?", default=None, help="Optional production ID")
    p_status.add_argument("--json", action="store_true", help="Output state as JSON")
    p_status.set_defaults(func=handle_status)

    p_list = sub.add_parser("list", help="List all productions and statuses")
    p_list.add_argument("--json", action="store_true", help="Output list as JSON")
    p_list.set_defaults(func=handle_list)

    p_prep = sub.add_parser("prepare", help="Prepare production package from approved script")
    p_prep.add_argument("-s", "--script-id", required=True, help="Approved script ID")
    p_prep.set_defaults(func=handle_prepare)

    p_val = sub.add_parser("validate", help="Run Gate inspections on production assets")
    p_val.add_argument("-p", "--production-id", required=True, help="Production ID to validate")
    p_val.set_defaults(func=handle_validate)

    p_ren = sub.add_parser("render", help="Trigger video rendering for prepared package")
    p_ren.add_argument("-p", "--production-id", required=True, help="Production ID to render")
    p_ren.set_defaults(func=handle_render)

    p_rep = sub.add_parser("report", help="Output detailed quality and production report")
    p_rep.add_argument("-p", "--production-id", required=True, help="Production ID")
    p_rep.set_defaults(func=handle_report)

    p_res = sub.add_parser("resume", help="Resume interrupted production from last valid checkpoint")
    p_res.add_argument("-p", "--production-id", required=True, help="Production ID to resume")
    p_res.add_argument("--confirm-approval", action="store_true", help="Confirm explicit human review sign-off")
    p_res.add_argument("-n", "--notes", default=None, help="Human reviewer notes when confirming approval")
    p_res.add_argument("--accept-warnings", action="store_true", help="Explicitly accept quality warnings")
    p_res.set_defaults(func=handle_resume)

    p_app = sub.add_parser("approve", help="Explicit human approval for verified production package")
    p_app.add_argument("-p", "--production-id", required=True, help="Production ID to approve")
    p_app.add_argument("-n", "--notes", required=True, help="Mandatory reviewer sign-off notes")
    p_app.add_argument("--accept-warnings", action="store_true", help="Explicitly accept quality warnings")
    p_app.set_defaults(func=handle_approve)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
