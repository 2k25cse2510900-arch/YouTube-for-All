"""YouTube API metadata transformation and formatting helper."""

from typing import Any, Dict, List, Optional
from config.settings import get_settings
from src.common.logger import setup_logger
from src.youtube_uploader.exceptions import YouTubeUploadError
from src.youtube_uploader.models import PrivacyStatus, UploadMetadata

logger = setup_logger("youtube_metadata_builder")


class MetadataBuilder:
    """Builds and validates YouTube Data API v3 snippet and status payloads."""

    @classmethod
    def build_resource_payload(
        cls,
        metadata: UploadMetadata,
        allow_public: bool = False,
    ) -> Dict[str, Any]:
        """Convert UploadMetadata into the YouTube Data API v3 video resource dict.

        Enforces security safeguards:
        - If privacy_status is PUBLIC but allow_public is False, raises YouTubeUploadError.
        - Ensures selfDeclaredMadeForKids is explicitly specified.
        - Appends #Shorts tag if absent to facilitate vertical Shorts shelf discovery.
        """
        # Security Guard: Public upload protection
        if metadata.privacy_status == PrivacyStatus.PUBLIC and not allow_public:
            raise YouTubeUploadError(
                "Public upload blocked by security safeguard. "
                "Default policy requires 'private'. To upload publicly, set allow_public=True and obtain explicit authorization."
            )

        # Ensure #Shorts is present in tags
        clean_tags = [t.strip() for t in metadata.tags if t.strip()]
        if "#Shorts" not in clean_tags and "Shorts" not in clean_tags:
            clean_tags.append("#Shorts")

        # Format resource dictionary
        payload: Dict[str, Any] = {
            "snippet": {
                "title": metadata.title,
                "description": metadata.description,
                "tags": clean_tags,
                "categoryId": metadata.category_id,
                "defaultLanguage": metadata.default_language,
                "defaultAudioLanguage": metadata.default_audio_language,
            },
            "status": {
                "privacyStatus": metadata.privacy_status.value,
                "selfDeclaredMadeForKids": metadata.made_for_kids,
                "embeddable": True,
            },
        }

        logger.debug(
            "Constructed YouTube resource payload: Title='%s', Privacy='%s', MadeForKids=%s",
            metadata.title,
            metadata.privacy_status.value,
            metadata.made_for_kids,
        )
        return payload
