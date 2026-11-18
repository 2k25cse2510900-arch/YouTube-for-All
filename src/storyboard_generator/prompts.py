"""Prompt engineering for Hindi/Hinglish script and storyboard generation."""

from typing import Optional

from src.research_engine.models import AnimeScienceDossier
from src.script_manager.models import Script
from src.storyboard_generator.pacing import PacingBudget

STORYBOARD_SYSTEM_PROMPT = """You are a senior anime-science video director and scriptwriter for YouTube Shorts ('A Lesson With AI').

Your task is to take an Anime Science Research Dossier and transform it into a high-retention, 30-60 second Hindi/Hinglish YouTube Short storyboard with cinematic image-generation prompts.

PRODUCTION STYLE:
- Image-based cinematic storytelling (one carefully composed image per scene, with subtle camera motion).
- No complex 3D character rigging or lip-sync.
- Language: Engaging, conversational Hinglish (Hindi written in Roman script, e.g. "Kya aapne socha hai...") with natural colloquial rhythm.

CRITICAL ARCHITECTURAL SAFEGUARDS:
1. SCIENTIFIC DEMARCATION & VERIFICATION:
   - Clearly separate anime fiction from empirical science in the script (e.g. "Anime mein to Senku ne 3,700 saal count kar liye, lekin real neuroscience mein...").
   - NEVER present unverified hypotheses as proven scientific dogma. Use appropriate scientific hedging in Hinglish (e.g. "Researchers ka manna hai...", "Current theories ke mutaabiq...").
   - Every scientific assertion must be mapped to an individual claim item.

2. VISUAL CONSISTENCY PROFILE:
   - Define a fixed Character Consistency Profile (character anchor, hairstyle, clothing, facial traits, color palette).
   - Design English image prompts for each scene that reference this anchor, specifying camera angle, framing, subject placement, and lighting in vertical 9:16 format.
   - Include negative prompts to prevent anatomical distortions, extra limbs, and watermarks.

3. DYNAMIC PACING & DURATION:
   - Adhere strictly to the requested word budget. Account for dramatic pauses between the hook, the scientific reveal, and the takeaway.
   - Divide the Short into 4 to 7 scenes. The sum of scene durations plus pause budget must exactly equal the target duration.

OUTPUT FORMAT:
Return a valid JSON object strictly matching this schema:
{
  "title": "Engaging Short Title",
  "hook": "Spoken hook line in Hinglish (0-4s)",
  "body": "Spoken explanation in Hinglish covering the science and anime contrast",
  "takeaway": "Closing punchline/call to reflection in Hinglish",
  "visual_consistency": {
    "character_name": "Name of character",
    "character_reference_image": null,
    "facial_features": "Detailed facial traits, eyes, markings",
    "hairstyle": "Hair color, texture, cut",
    "clothing_and_attire": "Exact garments and accessories",
    "color_palette": "Dominant color scheme",
    "art_direction": "Anime art style, lighting cues, 8k resolution, vertical 9:16",
    "negative_prompt": "distorted anatomy, extra limbs, deformed fingers, low resolution, blurry, watermark"
  },
  "scenes": [
    {
      "scene_number": 1,
      "narration_hinglish": "Spoken voiceover line for this scene in Hinglish",
      "narration_english_meaning": "English translation for review",
      "camera_angle": "low-angle / eye-level / high-angle / dutch-tilt",
      "framing": "extreme-close-up / medium-close-up / wide-establishing",
      "subject_placement": "center-weighted for vertical 9:16 mobile viewport",
      "image_prompt_positive": "Detailed English image generation prompt (subject, action, background, lighting, 9:16 vertical)",
      "image_prompt_negative": "Scene specific negative prompt",
      "suggested_duration_seconds": 6.5,
      "camera_movement": "slow_zoom_in / slow_zoom_out / pan_down / pan_up / static_drift",
      "sound_effect_cue": "[SFX: Stone cracking whoosh]"
    }
  ],
  "bgm_suggestion": {
    "mood": "Tense intro building into an inspiring revelation",
    "tempo": "120 BPM",
    "instrumentation": "Sub-bass pulse, clock ticking, electronic synth lead"
  },
  "scientific_claims": [
    {
      "claim": "Specific empirical assertion",
      "source_title": "Source reference title from research dossier",
      "source_type": "academic_paper|book|journal_article|educational_website|general_consensus|unverified_proposal",
      "url": null,
      "verification_status": "unverified",
      "is_verified": false
    }
  ]
}
"""


def build_storyboard_user_prompt(
    dossier: AnimeScienceDossier,
    pacing: PacingBudget,
) -> str:
    """Construct user prompt injecting research findings and calculated pacing targets."""
    claims_text = "\n".join([f"- {c.claim} (Source: {c.source_title})" for c in dossier.citations])

    prompt = f"""Generate an image-based YouTube Short storyboard and Hinglish narration script based on this research dossier:

RESEARCH DOSSIER:
- Topic: {dossier.topic}
- Anime Series: {dossier.anime_title}
- Character / Scene: {dossier.character_or_scene}
- Anime Canon Premise (Fiction): {dossier.anime_canon_premise}
- Real-World Science Explanation: {dossier.real_world_scientific_explanation}
- Demarcation Rule: {dossier.demarcation_warning}
- Research Claims:
{claims_text}

Pacing & Word Budget Targets:
- Target Video Duration: {pacing.target_duration_seconds} seconds
- Pause Budget: {pacing.pause_budget_seconds} seconds (for dramatic timing)
- Effective Spoken Time: {pacing.effective_speaking_seconds} seconds
- Target Spoken Words: {pacing.target_word_count} words (Acceptable range: {pacing.min_word_count} to {pacing.max_word_count} words)
- Number of Scenes: 4 to 6 scenes (Sum of suggested_duration_seconds must equal {pacing.target_duration_seconds - pacing.pause_budget_seconds:.1f}s)

IMPORTANT:
- Every scientific claim must start with verification_status='unverified' and is_verified=false.
- Narration must be natural, high-retention Hinglish.
- Return valid JSON matching the system schema.
"""
    return prompt


def build_storyboard_from_script_prompt(
    script: Script,
    pacing: PacingBudget,
) -> str:
    """Construct user prompt enforcing exact script narration as immutable source of truth."""
    citations_text = ""
    if script.research_references:
        citations_text = "\n".join([f"- {r.claim} (Source: {r.source_title or r.source})" for r in script.research_references])

    prompt = f"""You are directing an image-based YouTube Short storyboard from an APPROVED, IMMUTABLE script.

CRITICAL INSTRUCTION — DO NOT REWRITE OR CONDENSE THE NARRATION:
The narration text below has been human-approved. You MUST NOT shorten, summarize, paraphrase, or rewrite any sentence.
Your sole responsibility is to:
1. Divide the approved narration into sequential scenes (one image per scene).
2. Assign EVERY sentence from the Hook, Body, and Takeaway to exactly one scene, maintaining the exact original order.
3. Keep the exact words of Hook in Scene 1 and the exact words of Takeaway in the final scene.
4. Design detailed vertical 9:16 image generation prompts, camera movements, sound effect cues, and pacing durations for each scene.

APPROVED NARRATION (IMMUTABLE):
[HOOK]:
{script.hook}

[BODY]:
{script.body}

[TAKEAWAY]:
{script.takeaway}

SCIENTIFIC RESEARCH CITATIONS:
{citations_text if citations_text else 'No specific academic citations attached.'}

PACING TARGETS:
- Target Duration: {pacing.target_duration_seconds}s (Pause budget: {pacing.pause_budget_seconds}s)
- Total Spoken Word Count: {len(f"{script.hook} {script.body} {script.takeaway}".split())} words
- Each scene must carry its portion of the original narration verbatim.
- Return valid JSON matching the system schema.
"""
    return prompt

