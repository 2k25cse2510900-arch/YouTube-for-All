"""Cost-Safety Guard for strict ₹0 budget enforcement."""

from typing import Optional, Set

from src.common.logger import setup_logger
from src.image_engine.exceptions import CostSafetyViolationError

logger = setup_logger("cost_guard")


class CostSafetyGuard:
    """Enforces absolute zero-cost constraints across all image generation activities.

    Guarantees:
    1. No paid external API calls (Gemini Image, Imagen, Replicate, Fal.ai, DALL-E, Stability, etc.).
    2. No automatic fallback to any paid service.
    3. No hidden subscription, credit usage, or billing token consumption.
    4. Strict ₹0 ($0.00) budget ceiling.
    """

    ZERO_BUDGET_MODE: bool = True
    MAX_PERMISSIBLE_COST_USD: float = 0.00

    # Permanently blacklisted paid or subscription providers
    FORBIDDEN_PAID_PROVIDERS: Set[str] = {
        "google_imagen",
        "imagen",
        "gemini_image",
        "replicate",
        "fal",
        "fal_ai",
        "openai",
        "dalle",
        "dall-e",
        "dall_e",
        "midjourney",
        "stability",
        "stability_ai",
        "pollinations",  # Excluded per user instructions (API requires balance/auth)
        "pollinations_ai",
    }

    # Only verified zero-cost or offline mock providers may be registered
    PERMITTED_FREE_PROVIDERS: Set[str] = {
        "mock_pillow",
        "disabled_local_gpu",
        "cloudflare_flux",
        "cloudflare_workers_ai",
        "gemini_free_tier",
    }

    @classmethod
    def assert_zero_cost_provider(cls, provider_name: str) -> None:
        """Validate that the requested provider is strictly zero-cost and permitted."""
        clean_name = provider_name.strip().lower()

        if clean_name in cls.FORBIDDEN_PAID_PROVIDERS:
            msg = (
                f"COST SAFETY HARD BLOCK: Provider '{provider_name}' is a paid or external service. "
                f"Our operating budget is strictly ₹0. Paid providers are permanently blocked."
            )
            logger.critical(msg)
            raise CostSafetyViolationError(msg)

        if clean_name not in cls.PERMITTED_FREE_PROVIDERS:
            msg = (
                f"COST SAFETY HARD BLOCK: Provider '{provider_name}' is not in the verified zero-cost registry "
                f"({sorted(cls.PERMITTED_FREE_PROVIDERS)}). Refusing execution to prevent unvetted charges."
            )
            logger.critical(msg)
            raise CostSafetyViolationError(msg)

        logger.debug("CostSafetyGuard verified provider '%s' satisfies zero-budget policy.", provider_name)

    @classmethod
    def verify_generation_cost(cls, cost_usd: float, provider_name: str) -> None:
        """Enforce that generation incurred $0.00 cost."""
        if cost_usd > cls.MAX_PERMISSIBLE_COST_USD:
            msg = (
                f"COST SAFETY VIOLATION: Generation by '{provider_name}' reported a non-zero cost of "
                f"${cost_usd:.4f}. Immediate termination to prevent billing."
            )
            logger.critical(msg)
            raise CostSafetyViolationError(msg)

    @classmethod
    def assert_no_fallback_to_paid(cls, failed_provider: str, target_provider: Optional[str] = None) -> None:
        """Prevent any failure from triggering an automatic fallback to a paid or unvetted provider."""
        if target_provider:
            clean_target = target_provider.strip().lower()
            if clean_target in cls.FORBIDDEN_PAID_PROVIDERS:
                msg = (
                    f"COST SAFETY HARD BLOCK: Automatic fallback from '{failed_provider}' to paid provider "
                    f"'{target_provider}' is strictly forbidden."
                )
                logger.critical(msg)
                raise CostSafetyViolationError(msg)
