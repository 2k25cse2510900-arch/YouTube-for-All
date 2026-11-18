"""Character Bible specifying immutable visual identities for original anime characters."""

import json
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CharacterSpecification(BaseModel):
    """Immutable visual and narrative specification for an original anime character."""

    character_id: str = Field(..., min_length=1, description="Unique machine identifier for character")
    name: str = Field(..., min_length=1, description="Character's canonical display name")
    archetype: str = Field(..., description="Character archetype or class")
    gender: str = Field(default="female")
    apparent_age: str = Field(default="early 20s")
    
    # Visual specifications
    face_and_eyes: str = Field(..., description="Detailed facial geometry, eye shape, iris/pupil design, and default expression")
    hair_style: str = Field(..., description="Hair length, style, bangs, color, highlights, and dynamic behavior")
    clothing_and_gear: str = Field(..., description="Wardrobe layers, accessories, weaponry, and materials")
    body_proportions: str = Field(..., description="Height, build, posture, and kinetic silhouette")
    color_palette: List[str] = Field(default_factory=list, description="Primary, secondary, and accent hex color codes")
    distinguishing_features: List[str] = Field(default_factory=list, description="Tattoos, scars, implants, auras, unique items")
    
    # Asset references
    reference_image_paths: List[str] = Field(default_factory=list, description="Paths to canonical turnaround and expression sheets")
    approved_visual_variations: List[str] = Field(default_factory=list, description="Approved states: combat stance, damaged, awakened aura, etc.")

    def build_prompt_tokens(self, context_action: Optional[str] = None) -> str:
        """Generate high-adherence prompt conditioning string for diffusion models."""
        tokens = [
            f"character: {self.name}",
            f"{self.archetype}, {self.apparent_age}",
            f"face: {self.face_and_eyes}",
            f"hair: {self.hair_style}",
            f"attire: {self.clothing_and_gear}",
            f"proportions: {self.body_proportions}",
            f"distinctive: {', '.join(self.distinguishing_features)}",
            f"palette: {', '.join(self.color_palette)}",
            "style: high-end modern cinematic anime aesthetic, ufotable/mappa lighting, clean linework, 8k resolution"
        ]
        if context_action:
            tokens.append(f"action: {context_action}")
        return ", ".join(tokens)

    def build_negative_tokens(self) -> str:
        """Generate negative prompt tokens to eliminate off-model deformities."""
        return (
            "blurry, low quality, deformed anatomy, extra limbs, missing fingers, "
            "mutated hands, distorted face, inconsistent character design, western cartoon, "
            "photorealistic human face, 3d render, watermark, signature, ugly eyes, out of frame"
        )


class CharacterBible(BaseModel):
    """Collection of character specifications maintaining series-wide visual consistency."""

    title: str = Field(default="A Lesson With AI - Original Character Bible")
    universe: str = Field(default="Neo-Chrono Sci-Fi / Dark Fantasy")
    characters: Dict[str, CharacterSpecification] = Field(default_factory=dict)

    def add_character(self, spec: CharacterSpecification) -> None:
        self.characters[spec.character_id] = spec

    def get_character(self, character_id: str) -> Optional[CharacterSpecification]:
        return self.characters.get(character_id)

    def save_to_file(self, path: Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load_from_file(cls, path: Path) -> "CharacterBible":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return cls(**data)
