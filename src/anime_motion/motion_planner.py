"""Motion Planner defining cinematic shot choreography, motion tier classifications, and storyboard plans."""

from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class MotionType(str, Enum):
    """Programmatic taxonomy of visual motion tiers."""

    STATIC_IMAGE = "static_image"                          # Tier 1: Zero pixel motion
    CAMERA_MOTION = "camera_motion"                        # Tier 2: 2D affine pan/zoom over single canvas
    FRAME_INTERPOLATION = "frame_interpolation"            # Tier 3: Motion-compensated vector interpolation
    GENUINE_AI_ANIMATION = "genuine_ai_animation"          # Tier 4: Generative deforming character & particle motion


class ShotSize(str, Enum):
    """Cinematic camera shot framing."""

    WIDE = "wide"
    MEDIUM = "medium"
    CLOSE_UP = "close_up"
    EXTREME_CLOSE_UP = "extreme_close_up"
    DUTCH_ANGLE = "dutch_angle"
    OVER_THE_SHOULDER = "over_the_shoulder"


class MotionShotPlan(BaseModel):
    """Detailed cinematic specification for a single shot."""

    shot_idx: int = Field(..., ge=1, description="Sequential index of shot (1..N)")
    shot_id: str = Field(..., description="Unique slug for the shot, e.g. 'shot_01'")
    scene_id: str = Field(default="scene_01")
    time_start: float = Field(..., ge=0.0)
    time_end: float = Field(..., gt=0.0)
    duration: float = Field(..., gt=0.0)
    motion_type: MotionType = Field(default=MotionType.GENUINE_AI_ANIMATION)
    character_id: Optional[str] = Field(default=None)
    shot_size: ShotSize = Field(default=ShotSize.MEDIUM)
    
    # Choreography & Art Direction
    environment: str = Field(..., description="Location, architecture, weather, and background elements")
    camera_trajectory: str = Field(..., description="Camera movement: pan, tilt, track, crane, zoom")
    start_pose: str = Field(..., description="Initial pose and orientation of character or focal subject")
    intended_movement: str = Field(..., description="Dynamic action, limb articulation, facial expression change")
    end_pose: str = Field(..., description="Settle pose and termination state of the action")
    lighting: str = Field(..., description="Light source direction, color temperature, and contrast")
    
    # Audio Cues
    sfx_cue: Optional[str] = Field(default=None, description="Sound effect trigger: blade drawn, thunder, footsteps")
    music_direction: Optional[str] = Field(default=None, description="BGM intensity or ducking cue")
    narration_chunk: Optional[str] = Field(default=None, description="Spoken dialogue or voiceover coinciding with shot")
    
    # Prompt synthesis
    image_prompt: str = Field(..., description="Text prompt for initial keyframe synthesis")
    motion_prompt: str = Field(..., description="Motion conditioning prompt for I2V or video generation")
    continuity_notes: str = Field(default="", description="Strict visual elements carried over from preceding shot")


class MotionStoryboardPlan(BaseModel):
    """Full-length motion plan for an entire anime short."""

    storyboard_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    target_duration: float = Field(default=42.0, ge=30.0, le=60.0)
    language: str = Field(default="Hinglish", description="Target narration language: Hindi, Hinglish, English")
    shots: List[MotionShotPlan] = Field(default_factory=list)

    @property
    def total_shots(self) -> int:
        return len(self.shots)

    @property
    def genuine_animation_shots(self) -> int:
        return sum(1 for s in self.shots if s.motion_type == MotionType.GENUINE_AI_ANIMATION)

    @property
    def computed_duration(self) -> float:
        if not self.shots:
            return 0.0
        return round(self.shots[-1].time_end, 2)

    def validate_plan(self, raise_on_error: bool = False) -> Dict[str, Any]:
        """Verify compliance with minimum milestone requirements."""
        issues = []
        if self.total_shots < 15:
            issues.append(f"Insufficient shot count: {self.total_shots} (Minimum required: at least 15 shots)")
        if self.genuine_animation_shots < 8:
            issues.append(f"Insufficient genuine animation sequences: {self.genuine_animation_shots} (Target: 8-10)")
        if not (35.0 <= self.computed_duration <= 50.0):
            issues.append(f"Duration {self.computed_duration}s out of target window 35-50s")

        if raise_on_error and issues:
            raise ValueError(f"Plan validation failed: {'; '.join(issues)}")

        return {
            "valid": len(issues) == 0,
            "total_shots": self.total_shots,
            "genuine_animation_shots": self.genuine_animation_shots,
            "computed_duration": self.computed_duration,
            "target_duration_within_range": 35.0 <= self.computed_duration <= 50.0,
            "issues": issues,
        }

    def save_to_file(self, path: Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load_from_file(cls, path: Path) -> "MotionStoryboardPlan":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return cls(**data)
