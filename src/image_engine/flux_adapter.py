"""FLUX.1 Schnell Prompt Adaptation and Visual Conditioning Layer.

Translates scene visual descriptions into natural language descriptive prompts
optimized for FLUX.1 Schnell's T5-XXL text encoder, adhering to established anime
visual profiles (References 01, 02, and 03).
"""

from typing import Optional


class FluxPromptAdapter:
    """Adapts scene image prompts for FLUX.1 Schnell on Cloudflare Workers AI."""

    STYLE_PREFIX = (
        "High-end 2D Japanese anime keyframe illustration, professional studio animation aesthetic, "
        "crisp clean vector-like line art, vivid cel shading. "
    )

    COMPOSITION_VERTICAL_HINT = (
        "Vertical portrait orientation composition, center-weighted framing with ample top headroom for text graphics. "
    )

    SIGNATURE_CANVAS_HINT = (
        "Atmospheric dark navy blue background (#0B132B) with subtle glowing cyan grid coordinates and floating bokeh particles. "
    )

    GOJO_CHARACTER_ANCHOR = (
        "Silver-haired Protagonist from Supernatural Action Anime, recognizable spiky tousled pure snow-white hair, "
        "sleek black cloth blindfold covering his eyes, high-collared dark navy action anime sorcerer uniform, "
        "tall slender athletic build, calm confident aura. "
    )

    @classmethod
    def adapt_prompt(
        cls,
        base_prompt: str,
        character_name: Optional[str] = "Silver-haired Protagonist",
        is_vertical_short: bool = True,
        include_signature_canvas: bool = True,
    ) -> str:
        """Transform raw scene description into a high-fidelity FLUX.1 natural language prompt.
        
        FLUX.1 Schnell excels with coherent, descriptive prose rather than comma-separated tag soup.
        """
        parts = [cls.STYLE_PREFIX]

        if is_vertical_short:
            parts.append(cls.COMPOSITION_VERTICAL_HINT)

        if character_name and "protagonist" in character_name.lower():
            parts.append(cls.GOJO_CHARACTER_ANCHOR)

        # Clean and append base prompt
        cleaned_base = base_prompt.strip()
        # If the base prompt already has detailed text, integrate it smoothly
        if cleaned_base:
            parts.append(f"Scene action: {cleaned_base}. ")

        if include_signature_canvas:
            parts.append(cls.SIGNATURE_CANVAS_HINT)

        # Assemble and ensure length limits (max 2048 chars for Cloudflare schema)
        full_prompt = "".join(parts).strip()
        if len(full_prompt) > 2000:
            full_prompt = full_prompt[:2000]

        return full_prompt
