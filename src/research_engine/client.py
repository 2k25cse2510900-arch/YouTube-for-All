"""Resilient Gemini client wrapper leveraging the official google-genai SDK."""

import json
import logging
from typing import Any, Dict, Optional

from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import get_settings
from src.common.logger import setup_logger
from src.research_engine.exceptions import (
    GeminiAPIKeyMissingError,
    GeminiPermanentError,
    GeminiTransientError,
    ResearchParsingError,
)

logger = setup_logger("gemini_client")


def _is_transient_error(exc: BaseException) -> bool:
    """Determine whether an error is transient (e.g., 503, 429, timeouts)."""
    if isinstance(exc, (GeminiPermanentError, GeminiAPIKeyMissingError)):
        return False

    err_str = str(exc).lower()

    # Permanent indicators - never retry
    permanent_signals = ["401", "403", "404", "not_found", "not found", "invalid api key", "unauthenticated", "permission_denied", "bad request", "400"]
    if any(sig in err_str for sig in permanent_signals):
        return False

    # Transient indicators - retry with backoff
    transient_signals = ["503", "429", "504", "unavailable", "resource_exhausted", "high demand", "deadline_exceeded", "timeout", "timed out"]
    if any(sig in err_str for sig in transient_signals) or isinstance(exc, GeminiTransientError):
        return True

    return False


class GeminiResearchClient:
    """Client for generating research dossiers using Google Gemini API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.gemini.api_key
        self.model = model or settings.gemini.model  # Defaults to gemini-2.5-flash
        self.fallback_model = fallback_model or settings.gemini.fallback_model
        self.timeout_seconds = timeout_seconds or settings.gemini.timeout_seconds
        self.temperature = settings.gemini.temperature
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        """Initialize and cache the genai.Client securely."""
        if not self.api_key or not self.api_key.strip():
            raise GeminiAPIKeyMissingError(
                "GEMINI_API_KEY is not set. Please provide it in your .env file."
            )

        if self._client is None:
            # Client creation without logging the key, configured with request timeout in ms
            http_options = types.HttpOptions(timeout=int(self.timeout_seconds * 1000))
            self._client = genai.Client(api_key=self.api_key, http_options=http_options)
        return self._client

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=10),
        retry=retry_if_exception(_is_transient_error),
    )
    def _call_model(self, model_name: str, system_prompt: str, user_prompt: str) -> str:
        """Call Gemini model with tenacity retry for transient 503/429/timeout errors."""
        client = self._get_client()
        logger.info("Calling Gemini model '%s' (timeout: %ds)...", model_name, self.timeout_seconds)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self.temperature,
            response_mime_type="application/json",
        )

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=config,
            )

            if not response or not response.text:
                raise GeminiTransientError("Received empty response from Gemini API.")

            return response.text.strip()

        except Exception as e:
            err_msg = str(e)
            if _is_transient_error(e):
                logger.warning("Transient error on model '%s': %s. Retrying...", model_name, err_msg)
                raise GeminiTransientError(f"Transient Gemini failure: {err_msg}") from e
            elif any(sig in err_msg.lower() for sig in ["401", "403", "invalid api key"]):
                logger.error("Permanent authentication failure with Gemini API.")
                raise GeminiPermanentError(f"Authentication failure: {err_msg}") from e
            else:
                logger.error("Non-retriable error calling model '%s': %s", model_name, err_msg)
                raise

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Generate structured JSON, automatically attempting fallback model if primary fails."""
        raw_text = ""
        # 1. Attempt primary model
        try:
            raw_text = self._call_model(self.model, system_prompt, user_prompt)
        except Exception as primary_err:
            if isinstance(primary_err, GeminiAPIKeyMissingError):
                raise primary_err

            # Never fallback or retry if unauthorized/invalid credentials
            if any(sig in str(primary_err).lower() for sig in ["401", "invalid api key"]):
                raise primary_err

            if self.fallback_model and self.fallback_model != self.model:
                logger.warning(
                    "Primary model '%s' failed (%s). Attempting fallback model '%s'...",
                    self.model, primary_err, self.fallback_model
                )
                try:
                    raw_text = self._call_model(self.fallback_model, system_prompt, user_prompt)
                except Exception as fb_err:
                    raise GeminiTransientError(
                        f"Both primary ('{self.model}') and fallback ('{self.fallback_model}') failed: {fb_err}"
                    ) from fb_err
            else:
                raise primary_err

        # 2. Parse JSON response
        try:
            clean_json = raw_text
            # Remove Markdown code blocks if model wrapped JSON in ```json
            if clean_json.startswith("```"):
                clean_json = clean_json.strip("`")
                if clean_json.startswith("json"):
                    clean_json = clean_json[4:].strip()

            parsed = json.loads(clean_json)
            if not isinstance(parsed, dict):
                raise ResearchParsingError("Model output did not parse into a JSON object dictionary.")
            return parsed
        except json.JSONDecodeError as json_err:
            logger.error("Failed to parse Gemini response as JSON: %s", json_err)
            raise ResearchParsingError(f"Failed to decode model JSON: {json_err}. Raw: {raw_text[:200]}") from json_err
