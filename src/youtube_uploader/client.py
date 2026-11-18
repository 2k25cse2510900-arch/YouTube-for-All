"""YouTube Data API v3 OAuth Authentication Client Factory."""

from pathlib import Path
from typing import Any, List, Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config.settings import get_settings
from src.common.logger import setup_logger
from src.youtube_uploader.exceptions import AuthenticationError

logger = setup_logger("youtube_client")


class YouTubeClientFactory:
    """Manages Google OAuth 2.0 credentials and builds authenticated YouTube API client instances."""

    @classmethod
    def get_authenticated_service(
        cls,
        client_secret_path: Optional[Path] = None,
        token_path: Optional[Path] = None,
        scopes: Optional[List[str]] = None,
        interactive: bool = False,
    ) -> Any:
        """Load credentials and return an authorized YouTube Resource service object.

        Args:
            client_secret_path: Path to secrets/client_secret.json.
            token_path: Path to token.json.
            scopes: List of required OAuth scopes.
            interactive: If True and token is missing, opens local web browser for interactive login.
                         If False, strictly raises AuthenticationError without blocking.

        Returns:
            Resource: Google API client resource.

        Raises:
            AuthenticationError: If credentials or tokens cannot be securely loaded or refreshed.
        """
        settings = get_settings()
        secret_file = Path(client_secret_path or settings.paths.client_secret_file).resolve()
        tok_file = Path(token_path or settings.paths.token_file).resolve()
        req_scopes = scopes or settings.youtube.scopes

        if not secret_file.exists():
            msg = f"OAuth client secrets file not found at '{secret_file}'. Please verify secrets configuration."
            logger.error(msg)
            raise AuthenticationError(msg)

        credentials = None

        if tok_file.exists():
            try:
                credentials = Credentials.from_authorized_user_file(str(tok_file), req_scopes)
                logger.debug("Loaded existing OAuth credentials from '%s'.", tok_file.name)
            except Exception as err:
                logger.warning("Failed to parse token file '%s': %s", tok_file.name, err)
                credentials = None

        # Check validity and refresh if expired
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                logger.info("OAuth access token expired. Refreshing using refresh_token...")
                try:
                    credentials.refresh(Request())
                    tok_file.write_text(credentials.to_json(), encoding="utf-8")
                    logger.info("Successfully refreshed and updated '%s'.", tok_file.name)
                except RefreshError as r_err:
                    msg = f"Failed to refresh OAuth token: {r_err}. Re-authentication required."
                    logger.error(msg)
                    raise AuthenticationError(msg) from r_err
                except Exception as err:
                    msg = f"Unexpected error refreshing OAuth credentials: {err}"
                    logger.error(msg)
                    raise AuthenticationError(msg) from err
            else:
                if not interactive:
                    msg = (
                        f"No valid OAuth token found at '{tok_file}'. "
                        "Interactive authentication is disabled in automated execution mode."
                    )
                    logger.error(msg)
                    raise AuthenticationError(msg)

                # Interactive desktop authorization
                logger.info("Starting local interactive OAuth authorization flow...")
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), req_scopes)
                    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
                    tok_file.write_text(credentials.to_json(), encoding="utf-8")
                    logger.info("Interactive OAuth flow completed. Saved '%s'.", tok_file.name)
                except Exception as err:
                    msg = f"Interactive OAuth login failed: {err}"
                    logger.error(msg)
                    raise AuthenticationError(msg) from err

        try:
            # Build client service
            service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
            logger.info("YouTube Data API v3 service client initialized successfully.")
            return service
        except Exception as err:
            msg = f"Failed to construct YouTube API client: {err}"
            logger.error(msg)
            raise AuthenticationError(msg) from err
