"""Script Management and Storyboard Synthesis domain facade for YouTube-for-All."""
from src.script_manager.service import ScriptManager
from src.script_manager.parser import parse_script_file
from src.storyboard_generator.service import StoryboardGenerator
from src.storyboard_generator.fidelity import ScriptStoryboardFidelityValidator
from src.storyboard_generator.pacing import calculate_pacing_budget

__all__ = [
    "ScriptManager",
    "parse_script_file",
    "StoryboardGenerator",
    "ScriptStoryboardFidelityValidator",
    "calculate_pacing_budget",
]
