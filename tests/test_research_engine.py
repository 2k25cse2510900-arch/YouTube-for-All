"""Automated unit and integration tests for the Gemini Research Engine."""

import json
from unittest.mock import MagicMock, patch
import pytest

from src.research_engine import (
    AnimeScienceDossier,
    GeminiAPIKeyMissingError,
    GeminiPermanentError,
    GeminiResearchClient,
    GeminiTransientError,
    MotivationalThemeDossier,
    ResearchCitation,
    ResearchEngine,
    SourceType,
    VerificationStatus,
)


# --- 1. Citation Integrity & Guardrail Tests ---

def test_citation_unverified_guardrail():
    """Verify that all newly created AI citations default to unverified."""
    citation = ResearchCitation(
        claim="Human reaction time decreases under hypoxia.",
        source_title="Journal of Aviation Medicine",
        source_type=SourceType.JOURNAL_ARTICLE,
        verification_status=VerificationStatus.UNVERIFIED,
        is_verified=True,  # Attempting to mark as verified directly
    )

    # The model validator must enforce is_verified = False for unverified status
    assert citation.is_verified is False
    assert citation.verification_status == VerificationStatus.UNVERIFIED


def test_citation_human_verification_workflow():
    """Verify explicit human verification transitions citation state."""
    citation = ResearchCitation(
        claim="Bamboo roots grow underground for years before surface shoots appear.",
        source_title="Botanical Studies Handbook",
        source_type=SourceType.BOOK,
    )

    assert citation.is_verified is False
    assert citation.verification_status == VerificationStatus.UNVERIFIED

    # Human reviewer checks primary source
    citation.mark_verified_by_human("Verified in Botanical Review Vol 12, pp. 45-50.")
    assert citation.is_verified is True
    assert citation.verification_status == VerificationStatus.HUMAN_CHECKED
    assert "Botanical Review" in citation.verification_notes


def test_dossier_enforces_demarcation_warning():
    """Verify AnimeScienceDossier enforces demarcation between canon and science."""
    dossier = AnimeScienceDossier(
        dossier_id="test_dossier_01",
        topic="Petrification Consciousness",
        anime_title="Dr. Stone",
        character_or_scene="Senku counting seconds",
        anime_canon_premise="Human remains conscious in stone for 3,700 years.",
        scientific_domain="Cognitive Neuroscience",
        real_world_scientific_explanation="Sensory deprivation causes temporal distortion after hours.",
        citations=[
            ResearchCitation(
                claim="Sensory deprivation alters default mode network coherence.",
                source_title="Neuroscience Today",
                source_type=SourceType.ACADEMIC_PAPER,
            )
        ],
        suggested_creative_angles=["How does the brain measure time without external clocks?"],
    )

    assert dossier.dossier_id == "test_dossier_01"
    assert "CRITICAL" in dossier.demarcation_warning
    assert dossier.citations[0].is_verified is False


# --- 2. Client Authentication & Error Handling Tests ---

def test_missing_api_key_raises_error():
    """Verify client raises GeminiAPIKeyMissingError when no API key is provided."""
    client = GeminiResearchClient(api_key="")
    with pytest.raises(GeminiAPIKeyMissingError):
        client._get_client()


def test_permanent_error_not_retried():
    """Verify that permanent errors (e.g. 401 Unauthorized) are not retried."""
    client = GeminiResearchClient(api_key="fake-test-key")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("401 Invalid API Key: UNAUTHENTICATED")

    with patch.object(client, "_get_client", return_value=mock_client):
        with pytest.raises(GeminiPermanentError):
            client._call_model("gemini-2.5-flash", "system prompt", "user prompt")

    # generate_content should be called exactly once (no retry on permanent error)
    assert mock_client.models.generate_content.call_count == 1


def test_transient_error_retried_up_to_max_attempts():
    """Verify transient errors (503 High Demand) are retried 3 times."""
    import tenacity
    client = GeminiResearchClient(api_key="fake-test-key")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("503 UNAVAILABLE: Model high demand")

    with patch.object(client._call_model.retry, "wait", tenacity.wait_none()):
        with patch.object(client, "_get_client", return_value=mock_client):
            with pytest.raises(GeminiTransientError):
                client._call_model("gemini-2.5-flash", "system prompt", "user prompt")

    # Must retry exactly 3 times
    assert mock_client.models.generate_content.call_count == 3


def test_fallback_model_on_primary_failure():
    """Verify client attempts fallback model when primary model fails transients."""
    client = GeminiResearchClient(
        api_key="fake-test-key",
        model="gemini-2.5-flash",
        fallback_model="gemini-2.0-flash",
    )

    mock_response = MagicMock()
    mock_response.text = json.dumps({"topic": "Fallback Success", "citations": []})

    def mock_call(model_name, system_prompt, user_prompt):
        if model_name == "gemini-2.5-flash":
            raise GeminiTransientError("Primary 503 Overload")
        elif model_name == "gemini-2.0-flash":
            return mock_response.text
        raise ValueError(f"Unexpected model: {model_name}")

    with patch.object(client, "_call_model", side_effect=mock_call):
        data = client.generate_json("system", "user")

    assert data["topic"] == "Fallback Success"


# --- 3. Research Service Tests with Mocked LLM ---

def test_research_anime_science_service():
    """Verify ResearchEngine creates a structured AnimeScienceDossier with unverified citations."""
    mock_json = {
        "topic": "Gravity Acceleration & Blood Flow",
        "anime_title": "Dragon Ball Z",
        "character_or_scene": "Goku training under 100G gravity",
        "anime_canon_premise": "Body adapts to 100x Earth gravity through ki and conditioning.",
        "scientific_domain": "Cardiovascular Physiology & Biomechanics",
        "real_world_scientific_explanation": "Under 9G, blood pools in lower extremities causing G-LOC (loss of consciousness).",
        "demarcation_warning": "CRITICAL: 100G gravity would crush human skeletal structure instantly. Dragon Ball gravity mechanics are fictional.",
        "citations": [
            {
                "claim": "Human acceleration tolerance ceilings peak around 9G with anti-G straining maneuvers.",
                "source_title": "Fundamentals of Aerospace Medicine",
                "source_type": "book",
                "publication_details": "Davis et al., 4th Edition",
            }
        ],
        "suggested_creative_angles": [
            "Why is 9G the hard ceiling for the human cardiovascular system?",
            "What happens to fluid pressure when gravity multiplies?"
        ],
    }

    mock_client = MagicMock(spec=GeminiResearchClient)
    mock_client.generate_json.return_value = mock_json

    engine = ResearchEngine(client=mock_client)
    dossier = engine.research_anime_science(topic="100G Gravity Training", anime_title="Dragon Ball Z")

    assert isinstance(dossier, AnimeScienceDossier)
    assert dossier.anime_title == "Dragon Ball Z"
    assert dossier.scientific_domain == "Cardiovascular Physiology & Biomechanics"
    assert len(dossier.citations) == 1

    # Strict citation check: Must be unverified
    citation = dossier.citations[0]
    assert citation.source_title == "Fundamentals of Aerospace Medicine"
    assert citation.verification_status == VerificationStatus.UNVERIFIED
    assert citation.is_verified is False
    assert len(dossier.suggested_creative_angles) == 2


def test_research_motivational_theme_service():
    """Verify ResearchEngine creates a structured MotivationalThemeDossier."""
    mock_json = {
        "theme": "The Compound Effect of Invisible Growth",
        "psychological_or_natural_concept": "Subterranean Root Networking in Phyllostachys edulis (Moso Bamboo)",
        "real_world_evidence": "Bamboo develops rhizome networks for 3-5 years underground before vertical culm elongation.",
        "visual_metaphor_ideas": [
            "Dark cross-section of soil showing vast glowing white roots expanding while surface remains calm.",
            "Time-lapse of sudden vertical shooting after prolonged quiet."
        ],
        "citations": [
            {
                "claim": "Phyllostachys edulis rhizome expansion provides nutrient reserves for rapid vertical elongation.",
                "source_title": "Journal of Plant Physiology",
                "source_type": "journal_article",
            }
        ],
        "suggested_creative_angles": [
            "Why do we mistakenly label years of invisible preparation as 'overnight success'?"
        ],
    }

    mock_client = MagicMock(spec=GeminiResearchClient)
    mock_client.generate_json.return_value = mock_json

    engine = ResearchEngine(client=mock_client)
    dossier = engine.research_motivational_theme(theme="Invisible Patience")

    assert isinstance(dossier, MotivationalThemeDossier)
    assert dossier.theme == "The Compound Effect of Invisible Growth"
    assert len(dossier.visual_metaphor_ideas) == 2
    assert dossier.citations[0].is_verified is False


# --- 4. Opt-in Live Integration Handshake ---

@pytest.mark.integration
def test_live_gemini_handshake():
    """Live API test: ONLY run explicitly with `pytest -m integration`."""
    client = GeminiResearchClient()
    engine = ResearchEngine(client=client)

    dossier = engine.research_anime_science(
        topic="Senku time counting consciousness in stone",
        anime_title="Dr. Stone",
    )

    assert dossier.topic != ""
    assert dossier.anime_title == "Dr. Stone"
    assert len(dossier.citations) >= 1
    # Verify guardrail is active even on live outputs
    for cit in dossier.citations:
        assert cit.is_verified is False
        assert cit.verification_status == VerificationStatus.UNVERIFIED
