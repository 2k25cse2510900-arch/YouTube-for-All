"""Research Engine service coordinating anime science and motivational theme research."""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
import uuid

from src.common.logger import setup_logger
from src.research_engine.client import GeminiResearchClient
from src.research_engine.models import (
    AnimeScienceDossier,
    MotivationalThemeDossier,
    ResearchCitation,
    SourceType,
    VerificationStatus,
)
from src.research_engine.prompts import (
    ANIME_SCIENCE_SYSTEM_PROMPT,
    MOTIVATIONAL_THEME_SYSTEM_PROMPT,
    build_anime_science_prompt,
    build_motivational_theme_prompt,
)

logger = setup_logger("research_engine")


def _generate_dossier_id(prefix: str, name: str) -> str:
    """Generate a clean, deterministic or unique dossier ID."""
    clean_name = re.sub(r"[^\w\s-]", "", name.lower())
    clean_name = re.sub(r"[\s_]+", "_", clean_name).strip("_")[:30]
    random_suffix = uuid.uuid4().hex[:6]
    return f"{prefix}_{clean_name}_{random_suffix}"


class ResearchEngine:
    """Primary service for researching educational and motivational Shorts topics."""

    def __init__(self, client: Optional[GeminiResearchClient] = None):
        self.client = client or GeminiResearchClient()

    def _sanitize_citations(self, raw_citations: List[Dict[str, Any]]) -> List[ResearchCitation]:
        """Convert raw LLM citation outputs into ResearchCitation objects with strict unverified defaults."""
        citations = []
        for raw in raw_citations:
            if not isinstance(raw, dict):
                continue

            claim = raw.get("claim", "").strip()
            source_title = raw.get("source_title", "").strip()

            if not claim or not source_title:
                continue

            # Parse or map source type
            raw_type = raw.get("source_type", "unverified_proposal").lower()
            try:
                stype = SourceType(raw_type)
            except ValueError:
                stype = SourceType.UNVERIFIED_PROPOSAL

            citation = ResearchCitation(
                claim=claim,
                source_title=source_title,
                source_type=stype,
                url=raw.get("url"),
                publication_details=raw.get("publication_details"),
                # MANDATORY: AI-generated citations always start unverified
                verification_status=VerificationStatus.UNVERIFIED,
                is_verified=False,
                verification_notes="AI-generated citation: pending independent fact-checking against primary sources.",
            )
            citations.append(citation)

        return citations

    def research_anime_science(
        self,
        topic: str,
        anime_title: str = "",
    ) -> AnimeScienceDossier:
        """Research an anime topic, connecting fictional canon to empirical science.

        Returns an AnimeScienceDossier with strict separation between anime fiction
        and real-world scientific evidence.
        """
        logger.info("Conducting anime science research for topic: '%s' (Anime: '%s')", topic, anime_title or "Unspecified")

        user_prompt = build_anime_science_prompt(topic=topic, anime_title=anime_title)
        raw_json = self.client.generate_json(
            system_prompt=ANIME_SCIENCE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        dossier_id = _generate_dossier_id("dossier_anime", anime_title or topic)

        # Sanitize and guardrail citations
        raw_citations = raw_json.get("citations", [])
        guarded_citations = self._sanitize_citations(raw_citations)

        dossier = AnimeScienceDossier(
            dossier_id=dossier_id,
            topic=raw_json.get("topic", topic).strip(),
            anime_title=raw_json.get("anime_title", anime_title or "Anime Lore").strip(),
            character_or_scene=raw_json.get("character_or_scene", "General Concept").strip(),
            anime_canon_premise=raw_json.get("anime_canon_premise", "").strip(),
            scientific_domain=raw_json.get("scientific_domain", "Science & Mathematics").strip(),
            real_world_scientific_explanation=raw_json.get("real_world_scientific_explanation", "").strip(),
            demarcation_warning=raw_json.get(
                "demarcation_warning",
                "CRITICAL: The anime mechanics described are fictional canon and must never be conflated with empirical physical reality."
            ),
            citations=guarded_citations,
            suggested_creative_angles=raw_json.get("suggested_creative_angles", []),
        )

        logger.info(
            "Completed anime science dossier '%s' with %d unverified citations.",
            dossier.dossier_id, len(dossier.citations)
        )
        return dossier

    def research_motivational_theme(
        self,
        theme: str,
    ) -> MotivationalThemeDossier:
        """Research a motivational or personal growth theme.

        Identifies real-world psychological, biological, or natural backing and
        suggests 9:16 vertical visual metaphors.
        """
        logger.info("Conducting motivational theme research for theme: '%s'", theme)

        user_prompt = build_motivational_theme_prompt(theme=theme)
        raw_json = self.client.generate_json(
            system_prompt=MOTIVATIONAL_THEME_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        dossier_id = _generate_dossier_id("dossier_theme", theme)

        raw_citations = raw_json.get("citations", [])
        guarded_citations = self._sanitize_citations(raw_citations)

        dossier = MotivationalThemeDossier(
            dossier_id=dossier_id,
            theme=raw_json.get("theme", theme).strip(),
            psychological_or_natural_concept=raw_json.get("psychological_or_natural_concept", "").strip(),
            real_world_evidence=raw_json.get("real_world_evidence", "").strip(),
            visual_metaphor_ideas=raw_json.get("visual_metaphor_ideas", []),
            citations=guarded_citations,
            suggested_creative_angles=raw_json.get("suggested_creative_angles", []),
        )

        logger.info(
            "Completed motivational theme dossier '%s' with %d unverified citations.",
            dossier.dossier_id, len(dossier.citations)
        )
        return dossier
