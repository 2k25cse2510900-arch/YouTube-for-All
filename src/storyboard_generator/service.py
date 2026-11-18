"""Storyboard Generator service coordinating pacing, scene composition, and ScriptManager registration."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from config.settings import get_settings
from src.common.logger import setup_logger
from src.research_engine.client import GeminiResearchClient
from src.research_engine.models import AnimeScienceDossier, SourceType, VerificationStatus
from src.script_manager.models import ContentCategory, ResearchReference, SceneBreakdown, Script
from src.script_manager.service import ScriptManager
from src.storyboard_generator.exceptions import (
    PacingExceededError,
    ScriptFidelityError,
    StoryboardGenerationError,
    StoryboardValidationError,
)
from src.storyboard_generator.fidelity import (
    ScriptStoryboardFidelityValidator,
    compute_canonical_narration_checksum,
    extract_sentences,
)
from src.storyboard_generator.models import (
    CameraMovement,
    ScientificClaimVerification,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)
from src.storyboard_generator.pacing import (
    calculate_pacing_budget,
    check_narration_duration_limits,
    estimate_duration_from_narration,
    validate_combined_duration,
)
from src.storyboard_generator.prompts import (
    STORYBOARD_SYSTEM_PROMPT,
    build_storyboard_from_script_prompt,
    build_storyboard_user_prompt,
)


logger = setup_logger("storyboard_generator")


def _generate_storyboard_id(topic: str) -> str:
    """Generate a clean identifier for a storyboard."""
    clean = re.sub(r"[^\w\s-]", "", topic.lower())
    clean = re.sub(r"[\s_]+", "_", clean).strip("_")[:25]
    suffix = uuid.uuid4().hex[:6]
    return f"sb_anime_{clean}_{suffix}"


class StoryboardGenerator:
    """Orchestrator for creating production-ready scene storyboards and Hinglish scripts."""

    def __init__(
        self,
        client: Optional[GeminiResearchClient] = None,
        script_manager: Optional[ScriptManager] = None,
        base_dir: Optional[Path] = None,
    ):
        settings = get_settings()
        self.settings = settings
        self.client = client or GeminiResearchClient()
        self.script_manager = script_manager or ScriptManager()
        self.base_dir = Path(base_dir) if base_dir else settings.paths.processed_dir / "storyboards"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def generate_storyboard(
        self,
        dossier: AnimeScienceDossier,
        target_duration_seconds: float = 45.0,
        words_per_second: float = 2.2,
        pause_budget_seconds: float = 2.0,
        character_reference_image: Optional[str] = None,
    ) -> StoryboardDossier:
        """Transform an AnimeScienceDossier into a validated StoryboardDossier with image prompts and pacing."""
        logger.info(
            "Generating storyboard for '%s' (Target duration: %.1fs, pause budget: %.1fs)",
            dossier.topic, target_duration_seconds, pause_budget_seconds
        )

        # 1. Compute dynamic pacing targets
        pacing = calculate_pacing_budget(
            target_duration_seconds=target_duration_seconds,
            words_per_second=words_per_second,
            pause_budget_seconds=pause_budget_seconds,
        )

        user_prompt = build_storyboard_user_prompt(dossier=dossier, pacing=pacing)

        # 2. Call Gemini client for structured JSON
        raw_json = self.client.generate_json(
            system_prompt=STORYBOARD_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        storyboard_id = _generate_storyboard_id(dossier.topic)

        # 3. Parse and construct Visual Consistency Profile
        raw_vc = raw_json.get("visual_consistency", {})
        vc_profile = VisualConsistencyProfile(
            character_name=raw_vc.get("character_name", dossier.character_or_scene),
            character_reference_image=character_reference_image or raw_vc.get("character_reference_image"),
            facial_features=raw_vc.get("facial_features", "Characteristic anime facial features and expression"),
            hairstyle=raw_vc.get("hairstyle", "Anime signature hairstyle and color"),
            clothing_and_attire=raw_vc.get("clothing_and_attire", "Signature anime clothing attire"),
            color_palette=raw_vc.get("color_palette", "High-contrast cinematic colors"),
            art_direction=raw_vc.get(
                "art_direction",
                "Modern cinematic high-contrast anime key visual, volumetric rim lighting, 8k resolution, vertical 9:16"
            ),
            negative_prompt=raw_vc.get(
                "negative_prompt",
                "distorted anatomy, extra limbs, deformed hands, low resolution, blurry, watermark"
            ),
            aspect_ratio="9:16",
        )

        # 4. Parse scenes and normalize scene durations to fit target duration perfectly
        raw_scenes = raw_json.get("scenes", [])
        if not raw_scenes:
            raise StoryboardGenerationError("AI model response contained no scenes.")

        parsed_scenes: List[StoryboardScene] = []
        for s in raw_scenes:
            # Map camera movement enum safely
            cm_raw = s.get("camera_movement", "slow_zoom_in").lower()
            try:
                cm = CameraMovement(cm_raw)
            except ValueError:
                cm = CameraMovement.SLOW_ZOOM_IN

            scene = StoryboardScene(
                scene_number=s.get("scene_number", len(parsed_scenes) + 1),
                narration_hinglish=s.get("narration_hinglish", "").strip(),
                narration_english_meaning=s.get("narration_english_meaning", "").strip(),
                camera_angle=s.get("camera_angle", "eye-level"),
                framing=s.get("framing", "medium-close-up"),
                subject_placement=s.get("subject_placement", "center-weighted for vertical 9:16"),
                image_prompt_positive=s.get("image_prompt_positive", "").strip(),
                image_prompt_negative=s.get("image_prompt_negative", vc_profile.negative_prompt),
                suggested_duration_seconds=float(s.get("suggested_duration_seconds", 6.0)),
                camera_movement=cm,
                sound_effect_cue=s.get("sound_effect_cue"),
            )
            parsed_scenes.append(scene)

        # Normalize scene durations so sum(scenes) + pause_budget == target_duration_seconds
        available_scene_time = max(target_duration_seconds - pause_budget_seconds, 10.0)
        current_sum = sum(s.suggested_duration_seconds for s in parsed_scenes)
        if current_sum > 0 and abs(current_sum - available_scene_time) > 0.1:
            ratio = available_scene_time / current_sum
            for s in parsed_scenes:
                s.suggested_duration_seconds = round(s.suggested_duration_seconds * ratio, 2)

        # 5. Extract scientific claims and strictly enforce unverified default
        raw_claims = raw_json.get("scientific_claims", [])
        scientific_claims: List[ScientificClaimVerification] = []

        # First add all claims from the research dossier
        for cit in dossier.citations:
            scientific_claims.append(
                ScientificClaimVerification(
                    claim=cit.claim,
                    source_title=cit.source_title,
                    source_type=cit.source_type,
                    url=cit.url,
                    verification_status=VerificationStatus.UNVERIFIED,
                    is_verified=False,
                )
            )

        # If LLM proposed additional claims, add them as unverified as well
        for rc in raw_claims:
            claim_text = rc.get("claim", "").strip()
            if claim_text and not any(sc.claim.lower() == claim_text.lower() for sc in scientific_claims):
                raw_stype = rc.get("source_type", "unverified_proposal").lower()
                try:
                    stype = SourceType(raw_stype)
                except ValueError:
                    stype = SourceType.UNVERIFIED_PROPOSAL

                scientific_claims.append(
                    ScientificClaimVerification(
                        claim=claim_text,
                        source_title=rc.get("source_title", "AI Proposed Concept"),
                        source_type=stype,
                        url=rc.get("url"),
                        verification_status=VerificationStatus.UNVERIFIED,
                        is_verified=False,
                    )
                )

        # 6. Build Master Storyboard Dossier
        dossier_obj = StoryboardDossier(
            storyboard_id=storyboard_id,
            title=raw_json.get("title", f"{dossier.anime_title}: {dossier.topic}"),
            topic=dossier.topic,
            target_duration_seconds=target_duration_seconds,
            pause_budget_seconds=pause_budget_seconds,
            hook=raw_json.get("hook", parsed_scenes[0].narration_hinglish),
            body=raw_json.get("body", " ".join([s.narration_hinglish for s in parsed_scenes[1:-1]])),
            takeaway=raw_json.get("takeaway", parsed_scenes[-1].narration_hinglish),
            visual_consistency=vc_profile,
            scenes=parsed_scenes,
            bgm_suggestion=raw_json.get("bgm_suggestion", {}),
            scientific_claims=scientific_claims,
            demarcation_warning=dossier.demarcation_warning,
        )

        # 7. Persist storyboard JSON
        self._save_storyboard_file(dossier_obj)
        logger.info(
            "Storyboard '%s' successfully generated with %d scenes (Pacing: %d words, %.1fs combined).",
            dossier_obj.storyboard_id, len(dossier_obj.scenes), dossier_obj.total_spoken_words, dossier_obj.total_estimated_seconds
        )
        return dossier_obj

    def generate_storyboard_from_script(
        self,
        script: Script,
        words_per_second: float = 2.12,
        pause_budget_seconds: float = 2.0,
        character_reference_image: Optional[str] = None,
        storyboard_id: Optional[str] = None,
    ) -> StoryboardDossier:
        """Create a StoryboardDossier strictly preserving the approved Script as immutable source of truth."""
        full_text = f"{script.hook} {script.body} {script.takeaway}"
        is_within, est_duration, warning = check_narration_duration_limits(
            narration_text=full_text,
            words_per_second=words_per_second,
            pause_budget_seconds=pause_budget_seconds,
            max_duration_seconds=60.0,
        )
        if not is_within:
            logger.warning("Pacing limit warning: %s", warning)
            raise PacingExceededError(warning)

        target_duration = min(max(est_duration, 20.0), 60.0)
        pacing = calculate_pacing_budget(
            target_duration_seconds=target_duration,
            words_per_second=words_per_second,
            pause_budget_seconds=pause_budget_seconds,
        )

        sb_id = storyboard_id or _generate_storyboard_id(script.title)
        user_prompt = build_storyboard_from_script_prompt(script=script, pacing=pacing)

        raw_json = None
        try:
            raw_json = self.client.generate_json(
                system_prompt=STORYBOARD_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as err:
            logger.debug("AI client JSON generation unavailable (%s). Using deterministic sentence mapping.", err)

        # Build Visual Consistency Profile
        raw_vc = raw_json.get("visual_consistency", {}) if raw_json else {}
        vc_profile = VisualConsistencyProfile(
            character_name=raw_vc.get("character_name", "Host Professor AI"),
            character_reference_image=character_reference_image or raw_vc.get("character_reference_image"),
            facial_features=raw_vc.get("facial_features", "Expressive eyes, smart futuristic visor, engaging smile"),
            hairstyle=raw_vc.get("hairstyle", "Short neat silver hair"),
            clothing_and_attire=raw_vc.get("clothing_and_attire", "Dark grey tech hoodie with glowing cyan neon lines"),
            color_palette=raw_vc.get("color_palette", "Dark cinematic blue, cyan glow, charcoal black"),
            art_direction=raw_vc.get(
                "art_direction",
                "Anime art style, dramatic studio lighting, 8k resolution, vertical 9:16",
            ),
            negative_prompt=raw_vc.get(
                "negative_prompt",
                "distorted anatomy, extra limbs, deformed fingers, low resolution, blurry, watermark",
            ),
            aspect_ratio="9:16",
        )

        # Parse or construct scenes with 100% exact narration fidelity
        parsed_scenes: List[StoryboardScene] = []
        raw_scenes = raw_json.get("scenes", []) if raw_json else []

        use_raw_scenes = False
        if raw_scenes:
            sb_words = " ".join([s.get("narration_hinglish", "") for s in raw_scenes]).split()
            script_words = full_text.split()
            if len(sb_words) == len(script_words):
                use_raw_scenes = True

        if use_raw_scenes:
            for s in raw_scenes:
                cm_raw = s.get("camera_movement", "slow_zoom_in").lower()
                try:
                    cm = CameraMovement(cm_raw)
                except ValueError:
                    cm = CameraMovement.SLOW_ZOOM_IN

                parsed_scenes.append(
                    StoryboardScene(
                        scene_number=s.get("scene_number", len(parsed_scenes) + 1),
                        narration_hinglish=s.get("narration_hinglish", "").strip(),
                        narration_english_meaning=s.get("narration_english_meaning", "").strip(),
                        camera_angle=s.get("camera_angle", "eye-level"),
                        framing=s.get("framing", "medium-close-up"),
                        subject_placement=s.get("subject_placement", "center-weighted for vertical 9:16"),
                        image_prompt_positive=s.get("image_prompt_positive", "").strip(),
                        image_prompt_negative=s.get("image_prompt_negative", vc_profile.negative_prompt),
                        suggested_duration_seconds=float(s.get("suggested_duration_seconds", 6.0)),
                        camera_movement=cm,
                        sound_effect_cue=s.get("sound_effect_cue"),
                    )
                )
        else:
            # Deterministic sentence partitioning preserving 100% script fidelity
            hook_s = extract_sentences(script.hook)
            body_s = extract_sentences(script.body)
            takeaway_s = extract_sentences(script.takeaway)

            scenes_data: List[Tuple[str, str, CameraMovement, str]] = []
            
            # Scene 1: Hook
            scenes_data.append((
                " ".join(hook_s),
                f"Opening visual establishing premise for '{script.title}', massive titan peering over burning fortress wall, high contrast anime style, vertical 9:16",
                CameraMovement.SLOW_ZOOM_IN,
                "[SFX: Dramatic titan roar and rumble]",
            ))

            # Body scenes (partition cleanly)
            if len(body_s) <= 3:
                for idx, b_sent in enumerate(body_s, 2):
                    scenes_data.append((
                        b_sent,
                        f"Scientific explanation scene {idx} showing physics and diagrams, anime style, vertical 9:16",
                        CameraMovement.STATIC_DRIFT if idx % 2 == 0 else CameraMovement.PAN_UP,
                        "[SFX: Scientific revelation sound]",
                    ))
            else:
                # 4 body sentences -> 3 body scenes
                scenes_data.append((
                    body_s[0],
                    f"Futuristic anime laboratory with scientist observing holographic data, cyan glow, vertical 9:16",
                    CameraMovement.STATIC_DRIFT,
                    "[SFX: Futuristic digital scan hum]",
                ))
                scenes_data.append((
                    body_s[1],
                    f"Mathematical 3D geometric wireframe cubes scaling exponentially, volumetric lighting, vertical 9:16",
                    CameraMovement.PAN_UP,
                    "[SFX: Heavy mechanical gear creaking]",
                ))
                scenes_data.append((
                    " ".join(body_s[2:]),
                    f"Massive fantasy skeletal titan buckling and collapsing under extreme gravity, red warning lighting, vertical 9:16",
                    CameraMovement.SLOW_ZOOM_OUT,
                    "[SFX: Structural crunch and deep bass drop]",
                ))

            # Takeaway Scene
            scenes_data.append((
                " ".join(takeaway_s),
                f"Professor AI host concluding takeaway with friendly smile and high-tech anime background, vertical 9:16",
                CameraMovement.SLOW_ZOOM_IN,
                "[SFX: Inspiring scientific chime]",
            ))

            # Assign proportional durations to scenes
            total_words_count = len(full_text.split())
            available_speech = target_duration - pause_budget_seconds
            for s_idx, (s_text, prompt_pos, cam_mov, sfx) in enumerate(scenes_data, 1):
                w_count = len(s_text.split())
                dur = round((w_count / total_words_count) * available_speech, 2)
                parsed_scenes.append(
                    StoryboardScene(
                        scene_number=s_idx,
                        narration_hinglish=s_text,
                        narration_english_meaning=s_text,
                        camera_angle="eye-level" if s_idx % 2 == 0 else "low-angle",
                        framing="medium-close-up" if s_idx != 3 else "wide-establishing",
                        subject_placement="center-weighted for vertical 9:16 mobile viewport",
                        image_prompt_positive=prompt_pos,
                        image_prompt_negative=vc_profile.negative_prompt,
                        suggested_duration_seconds=dur,
                        camera_movement=cam_mov,
                        sound_effect_cue=sfx,
                    )
                )

        # Normalize scene durations so sum(scenes) + pause_budget == target_duration
        available_scene_time = max(target_duration - pause_budget_seconds, 10.0)
        current_sum = sum(s.suggested_duration_seconds for s in parsed_scenes)
        if current_sum > 0 and abs(current_sum - available_scene_time) > 0.1:
            ratio = available_scene_time / current_sum
            for s in parsed_scenes:
                s.suggested_duration_seconds = round(s.suggested_duration_seconds * ratio, 2)

        # Map scientific claims from script
        scientific_claims: List[ScientificClaimVerification] = []
        for ref in script.research_references:
            scientific_claims.append(
                ScientificClaimVerification(
                    claim=ref.claim,
                    source_title=ref.source_title or ref.source or "Scientific Reference",
                    source_type=SourceType.ACADEMIC_PAPER,
                    url=ref.source_url or ref.source,
                    verification_status=VerificationStatus.HUMAN_CHECKED if ref.is_verified else VerificationStatus.UNVERIFIED,
                    is_verified=ref.is_verified,
                    human_reviewer_notes=ref.notes,
                )
            )

        # Assemble master dossier
        script_checksum = compute_canonical_narration_checksum(full_text)
        storyboard_narration = " ".join([s.narration_hinglish for s in parsed_scenes])
        sb_checksum = compute_canonical_narration_checksum(storyboard_narration)

        dossier_obj = StoryboardDossier(
            storyboard_id=sb_id,
            title=script.title,
            topic=script.title,
            target_duration_seconds=target_duration,
            pause_budget_seconds=pause_budget_seconds,
            hook=script.hook,
            body=script.body,
            takeaway=script.takeaway,
            visual_consistency=vc_profile,
            scenes=parsed_scenes,
            bgm_suggestion={
                "mood": "Tense anime action building into a fascinating scientific realization",
                "tempo": "125 BPM",
                "instrumentation": "Punchy orchestral strings, heavy electronic synth bass, ticking clock",
            },
            scientific_claims=scientific_claims,
            demarcation_warning="CRITICAL: Anime mechanics are fictional canon. Real-world empirical science must be explicitly separated in presentation.",
            source_script_id=script.id,
            source_script_checksum=script.content_hash,
            source_script_version="1.0",
            source_narration_checksum=script_checksum,
            storyboard_narration_checksum=sb_checksum,
            narration_fidelity_status="VERIFIED",
        )

        # Enforce Fidelity Validation before persisting
        ScriptStoryboardFidelityValidator.validate_fidelity(script=script, storyboard=dossier_obj, raise_on_error=True)

        self._save_storyboard_file(dossier_obj)
        logger.info(
            "Storyboard '%s' generated from script '%s' with %d scenes (Pacing: %d words, %.1fs combined, Fidelity: VERIFIED).",
            dossier_obj.storyboard_id,
            script.id,
            len(dossier_obj.scenes),
            dossier_obj.total_spoken_words,
            dossier_obj.total_estimated_seconds,
        )
        return dossier_obj


    def _save_storyboard_file(self, dossier: StoryboardDossier) -> Path:
        """Persist full storyboard dossier JSON."""
        file_path = self.base_dir / f"{dossier.storyboard_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(dossier.model_dump_json(indent=2))
        return file_path

    def get_storyboard(self, storyboard_id: str) -> Optional[StoryboardDossier]:
        """Load a persisted storyboard by ID."""
        file_path = self.base_dir / f"{storyboard_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return StoryboardDossier(**data)

    def register_with_script_manager(
        self,
        storyboard: StoryboardDossier,
    ) -> Script:
        """Transform StoryboardDossier into a Script and register with ScriptManager.

        CRITICAL: submit_ai_draft() guarantees the script enters PENDING_REVIEW
        and cannot enter the production queue without human approval.
        """
        logger.info("Registering storyboard '%s' with ScriptManager...", storyboard.storyboard_id)

        # Map scenes to standard SceneBreakdown
        standard_scenes = [
            SceneBreakdown(
                scene_number=s.scene_number,
                visual_prompt=f"{storyboard.visual_consistency.art_direction}. {s.image_prompt_positive}",
                narration=s.narration_hinglish,
                estimated_seconds=s.suggested_duration_seconds,
            )
            for s in storyboard.scenes
        ]

        # Map scientific claims to standard ResearchReference
        research_refs = [
            ResearchReference(
                claim=sc.claim,
                source=sc.source_title,
                is_verified=sc.is_verified,
                notes=sc.human_reviewer_notes or "AI Sourced - Requires Human Verification",
            )
            for sc in storyboard.scientific_claims
        ]

        script_payload: Dict[str, Any] = {
            "id": storyboard.storyboard_id,
            "title": storyboard.title,
            "category": ContentCategory.ANIME_SCIENCE.value,
            "hook": storyboard.hook,
            "body": storyboard.body,
            "takeaway": storyboard.takeaway,
            "scenes": [s.model_dump() for s in standard_scenes],
            "research_references": [r.model_dump() for r in research_refs],
            "tags": ["#Shorts", "#AnimeScience", f"#{re.sub(r'[^a-zA-Z0-9]', '', storyboard.topic)}"],
            "target_duration_seconds": storyboard.target_duration_seconds,
            "estimated_duration_seconds": storyboard.total_estimated_seconds,
            "metadata": {
                "storyboard_id": storyboard.storyboard_id,
                "has_unverified_claims": storyboard.has_unverified_claims,
                "claims_pending_verification": storyboard.claims_pending_verification,
                "visual_consistency": storyboard.visual_consistency.model_dump(),
                "bgm_suggestion": storyboard.bgm_suggestion,
                "demarcation_warning": storyboard.demarcation_warning,
            },
        }

        # Submits draft strictly into PENDING_REVIEW
        saved_script = self.script_manager.submit_ai_draft(script_payload)
        logger.info(
            "Storyboard successfully registered as Script '%s' in PENDING_REVIEW status.",
            saved_script.id
        )
        return saved_script
