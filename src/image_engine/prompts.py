"""Prompt synthesis combining Visual Consistency profiles and Scene cinematography."""

from typing import Tuple

from src.storyboard_generator.models import StoryboardScene, VisualConsistencyProfile


def build_scene_image_prompt(
    visual_consistency: VisualConsistencyProfile,
    scene: StoryboardScene,
) -> Tuple[str, str]:
    """Synthesize complete positive and negative prompts for a scene.

    Ensures:
    1. Universal art direction and character appearance consistency.
    2. Scene-specific cinematography (camera angle, framing, subject placement).
    3. Center-weighted framing safe for 9:16 vertical mobile viewports.
    4. Merged scene-specific and global negative prompts.
    """
    # 1. Compose Character Consistency descriptors
    char_desc = (
        f"Character: {visual_consistency.character_name}. "
        f"Appearance: {visual_consistency.facial_features}, {visual_consistency.hairstyle}. "
        f"Attire: {visual_consistency.clothing_and_attire}. "
        f"Color Palette: {visual_consistency.color_palette}."
    )

    # 2. Compose Cinematography and Composition cues
    cinematography = (
        f"Composition: {scene.camera_angle} camera angle, {scene.framing} shot, "
        f"{scene.subject_placement}, vertical 9:16 mobile framing with safe UI margins."
    )

    # 3. Assemble Full Positive Prompt
    positive_parts = [
        visual_consistency.art_direction.strip().rstrip("."),
        char_desc.strip().rstrip("."),
        scene.image_prompt_positive.strip().rstrip("."),
        cinematography.strip().rstrip("."),
        "8k resolution, vertical 9:16 aspect ratio, masterpiece",
    ]
    positive_prompt = ". ".join(p for p in positive_parts if p)

    # 4. Assemble Full Negative Prompt
    neg_parts = []
    if visual_consistency.negative_prompt:
        neg_parts.append(visual_consistency.negative_prompt.strip().rstrip(","))
    if scene.image_prompt_negative and scene.image_prompt_negative != visual_consistency.negative_prompt:
        neg_parts.append(scene.image_prompt_negative.strip().rstrip(","))

    # Standard universal hygiene against distorted anatomy and text
    neg_parts.append("horizontal composition, wide landscape, borders, letterboxing, deformed anatomy, extra limbs")

    negative_prompt = ", ".join(p for p in neg_parts if p)

    return positive_prompt, negative_prompt
