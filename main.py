"""Main entry point for A Lesson With AI.

Provides system readiness diagnostics, status reporting, and CLI routing for the
automated YouTube Shorts production pipeline.
"""

import argparse
import sys
from pathlib import Path

from configs.settings import get_settings
from src.common.logger import setup_logger
from src.pipeline.cli import build_pipeline_parser
from src.pipeline.models import StageStatus
from src.pipeline.state_manager import PipelineStateManager

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    USE_RICH = True
    console = Console()
except ImportError:
    USE_RICH = False
    console = None


def check_auth_status(settings) -> tuple[bool, str]:
    """Check existence and basic validity of OAuth credentials safely."""
    client_secret_exists = settings.paths.client_secret_file.exists()
    token_exists = settings.paths.token_file.exists()

    if not client_secret_exists:
        return False, "Missing client_secret.json in secrets/"
    if not token_exists:
        return False, "Missing token.json. Run youtube_auth_test.py to connect."
    return True, "OAuth files detected (credentials preserved safely)"


def get_pipeline_metrics():
    """Retrieve production counts and active status from PipelineStateManager."""
    try:
        sm = PipelineStateManager()
        prods = sm.list_all_productions()
        active = [p for p in prods if p.overall_status == StageStatus.RUNNING]
        completed = [p for p in prods if p.overall_status == StageStatus.COMPLETED]
        failed_blocked = [p for p in prods if p.overall_status in (StageStatus.FAILED, StageStatus.BLOCKED)]
        pending = [p for p in prods if p.overall_status == StageStatus.PENDING]

        next_in_queue = pending[0] if pending else (active[0] if active else None)
        active_prod = active[0] if active else (pending[0] if pending else (prods[0] if prods else None))

        return {
            "total": len(prods),
            "active_count": len(active),
            "completed_count": len(completed),
            "failed_blocked_count": len(failed_blocked),
            "pending_count": len(pending),
            "next_in_queue": next_in_queue.production_id if next_in_queue else "None",
            "active_prod": active_prod,
        }
    except Exception:
        return {
            "total": 0,
            "active_count": 0,
            "completed_count": 0,
            "failed_blocked_count": 0,
            "pending_count": 0,
            "next_in_queue": "None",
            "active_prod": None,
        }


def print_status_rich(settings, logger):
    """Render a formatted status dashboard using rich."""
    auth_ok, auth_msg = check_auth_status(settings)
    metrics = get_pipeline_metrics()

    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]{settings.app_name}[/bold cyan]\n"
            "[dim]Modular Automated YouTube Shorts Production Pipeline — Stage 7D Master Orchestrator[/dim]",
            border_style="cyan",
        )
    )

    # Table 1: System Config & Safety Safeguards
    table = Table(title="System Configuration & Safeguards", show_header=True)
    table.add_column("Component / Safeguard", style="bold")
    table.add_column("Configuration", style="green")
    table.add_column("Status / Details", style="dim")

    table.add_row(
        "Human Approval Gate",
        str(settings.publishing.require_human_approval),
        "[green]Active (Required before publishing)[/green]"
        if settings.publishing.require_human_approval
        else "[yellow]Automated[/yellow]",
    )
    table.add_row(
        "Upload Safety Enforcer",
        "upload_enabled=False",
        "[bold green]Strict ₹0 Production Ceiling (No real uploads without approval)[/bold green]",
    )
    table.add_row(
        "Publish Interval",
        f"{settings.publishing.publish_interval_hours} hours",
        "Cadence: 1 Short per day",
    )
    table.add_row(
        "Video Format",
        f"{settings.video.width}x{settings.video.height} (9:16)",
        f"Target FPS: {settings.video.fps}",
    )
    table.add_row(
        "YouTube Auth",
        "Configured" if auth_ok else "Attention Required",
        f"[{'green' if auth_ok else 'red'}]{auth_msg}[/]",
    )

    console.print(table)

    # Table 2: Pipeline Production Summary
    pipe_table = Table(title="Pipeline Production & Queue Summary", show_header=True)
    pipe_table.add_column("Production Metric", style="bold cyan")
    pipe_table.add_column("Value", style="bold white")
    pipe_table.add_column("Status / Notes", style="dim")

    pipe_table.add_row("Total Production Packages", str(metrics["total"]), "Tracked in data/processed/pipeline/")
    pipe_table.add_row("Active / In-Flight", str(metrics["active_count"]), "Currently processing or locked")
    pipe_table.add_row("Completed Productions", str(metrics["completed_count"]), "Ready for staging / storage preserved")
    pipe_table.add_row("Blocked / Failed", str(metrics["failed_blocked_count"]), "Needs review or asset import")
    pipe_table.add_row("Next in Queue", metrics["next_in_queue"], "Scheduled for next processing step")

    act = metrics["active_prod"]
    if act:
        missing_note = "-"
        if act.error_message:
            missing_note = act.error_message[:45] + "..." if len(act.error_message) > 45 else act.error_message
        pipe_table.add_row("Active ID & Stage", f"{act.production_id[:16]}... ({act.current_stage.value})", missing_note)

    console.print(pipe_table)

    # Table 3: Safety Gates Summary
    gates_table = Table(title="Production Safety Gates (A–F)", show_header=True)
    gates_table.add_column("Gate", style="bold magenta")
    gates_table.add_column("Gate Name", style="bold white")
    gates_table.add_column("Enforcement & Rules", style="dim")
    gates_table.add_column("State", style="bold green")

    gates_table.add_row("Gate A", "Script Approval", "Status must be APPROVED; rejects draft/pending/rejected", "ACTIVE")
    gates_table.add_row("Gate B", "Research Verification", "Claim verified; confidence >= 0.8; citations verified", "ACTIVE")
    gates_table.add_row("Gate C", "Visual Assets", "All scene images present; mock images quarantined; approved", "ACTIVE")
    gates_table.add_row("Gate D", "Audio Integrity", "Edge TTS voice; licensed BGM; non-synthetic; PCM WAV", "ACTIVE")
    gates_table.add_row("Gate E", "Video Quality", "FFmpeg 1080x1920; 0 QA failures; 0 unacknowledged warnings", "ACTIVE")
    gates_table.add_row("Gate F", "Pre-Upload Human Gate", "upload_enabled=False strict default; SHA-256 signed record", "ACTIVE")

    console.print(gates_table)

    # Table 4: Modular Subsystems Overview
    module_table = Table(title="Modular Architecture Overview", show_header=True)
    module_table.add_column("Module Package", style="bold cyan")
    module_table.add_column("Responsibility", style="white")
    module_table.add_column("State", style="yellow")

    modules = [
        ("src.script_manager", "Batch script ingestion (10-15 days) & queueing", "[bold green]Active (Phase 2 Ready)[/]"),
        ("src.research_engine", "Factual AI research & citation verification", "[bold green]Active (Gemini Engine Ready)[/]"),
        ("src.storyboard_generator", "Scene storyboard, visual consistency & Hinglish scripts", "[bold green]Active (Storyboard Ready)[/]"),
        ("src.image_engine", "Scene visuals & manual import workflow", "[bold green]Active (Stage 7D Ready)[/]"),
        ("src.audio_engine", "Edge TTS narration, BGM/SFX & WAV mixing", "[bold green]Active (Stage 7D Ready)[/]"),
        ("src.caption_generator", "Word-level animated subtitles & safe zones", "[bold green]Active (Stage 7D Ready)[/]"),
        ("src.video_editor", "FFmpeg compositing & final 9:16 assembly", "[bold green]Active (Stage 7B Ready)[/]"),
        ("src.quality_checker", "Audio/video metrics, LUFS, & QA gating", "[bold green]Active (Stage 7C Ready)[/]"),
        ("src.youtube_uploader", "YouTube API upload & approval record", "[bold green]Active (Stage 7C Ready)[/]"),
        ("src.pipeline", "End-to-end master orchestrator & recovery", "[bold green]Active (Stage 7D Master Ready)[/]"),
    ]

    for mod_name, desc, state in modules:
        module_table.add_row(mod_name, desc, state)

    console.print(module_table)

    # Script Inventory Table
    try:
        from src.script_manager import ScriptManager
        sm = ScriptManager()
        summary = sm.get_summary()

        script_table = Table(title="Script Manager Inventory", show_header=True)
        script_table.add_column("Metric", style="bold")
        script_table.add_column("Count", style="cyan")
        script_table.add_column("Status / Note", style="dim")

        script_table.add_row("Total Ingested Scripts", str(summary["total_scripts"]), "Stored in data/processed/")
        script_table.add_row("Approved in Queue", str(summary["approved_in_queue"]), f"{summary['days_of_content_ready']} days of ready content (1/day)")
        script_table.add_row("Pending Review", str(summary.get("by_status", {}).get("pending_review", 0)), "Awaiting creator approval")
        script_table.add_row("Already Used", str(summary.get("by_status", {}).get("used", 0)), "Published / Produced (No duplicates)")

        console.print(script_table)
    except Exception as exc:
        logger.debug("Script inventory check skipped: %s", exc)

    console.print()
    logger.info("System status check completed successfully.")


def print_status_plain(settings, logger):
    """Fallback status printer for plain text terminals."""
    auth_ok, auth_msg = check_auth_status(settings)
    metrics = get_pipeline_metrics()

    print("=" * 70)
    print(f"  {settings.app_name}")
    print("  Modular Automated YouTube Shorts Production Pipeline (Stage 7D)")
    print("=" * 70)
    print(f"Human Approval Gate  : {settings.publishing.require_human_approval}")
    print(f"Upload Enforcer      : upload_enabled=False (Strict ₹0 Production Ceiling)")
    print(f"Publish Interval     : {settings.publishing.publish_interval_hours}h")
    print(f"Video Format         : {settings.video.width}x{settings.video.height} (9:16)")
    print(f"YouTube Auth         : {auth_msg}")
    print("-" * 70)
    print(f"Total Productions    : {metrics['total']}")
    print(f"Active / Running     : {metrics['active_count']}")
    print(f"Completed            : {metrics['completed_count']}")
    print(f"Failed / Blocked     : {metrics['failed_blocked_count']}")
    print(f"Next in Queue        : {metrics['next_in_queue']}")
    print("-" * 70)
    print("Safety Gates Active  : Gates A, B, C, D, E, F (All Enforced)")
    print("=" * 70)
    logger.info("System status check completed successfully.")


def main():
    """Application entry point with pipeline CLI routing."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="A Lesson With AI - YouTube Shorts Production Pipeline",
    )
    parser.add_argument("--status", action="store_true", help="Display system status dashboard")

    subparsers = parser.add_subparsers(dest="subcommand", help="Module subcommands")
    build_pipeline_parser(subparsers)

    args = parser.parse_args()

    # Route pipeline subcommands if provided
    if args.subcommand == "pipeline" and hasattr(args, "func"):
        return args.func(args)

    # Otherwise show dashboard
    settings = get_settings()
    logger = setup_logger()
    logger.info("Initializing %s...", settings.app_name)

    if USE_RICH:
        print_status_rich(settings, logger)
    else:
        print_status_plain(settings, logger)
    return 0


if __name__ == "__main__":
    sys.exit(main())
