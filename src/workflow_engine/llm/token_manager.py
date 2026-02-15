"""
LLM Token Manager

Unified token management for all LLM providers with support for:
- Azure OpenAI OAuth2 authentication 
- API key authentication
- Token caching and automatic refresh
- Multiple authentication endpoints
"""

import asyncio
import base64
import json
import time
from typing import Optional
import requests

from ..core.schemas import LLMConfig
from ..shared.utils.logging import get_logger

logger = get_logger(__name__)


class LLMTokenManager:
    """Unified token management for all LLM providers."""
    
    def __init__(self, llm_config: LLMConfig):
        self.config = llm_config
        self._cached_token = None
        self._token_expires_at = 0
        self._token_buffer_seconds = 300  # Refresh 5 minutes before expiry
    
    async def get_token(self) -> str:
        """Get access token based on provider and authentication method."""
        
        if self.config.provider == "azure_openai":
            if self.config.api_key:
                # Direct API key - no token refresh needed
                return self.config.api_key
            else:
                # OAuth2 flow
                return await self._get_oauth2_token()
        else:
            # For other providers, return API key directly
            return self.config.api_key or ""
    
    async def _get_oauth2_token(self) -> str:
        """Get OAuth2 token for Azure OpenAI with caching."""
        current_time = time.time()
        
        # Return cached token if still valid
        if (self._cached_token and 
            current_time < (self._token_expires_at - self._token_buffer_seconds)):
            logger.debug("Using cached OAuth2 token")
            return self._cached_token
        
        # Validate OAuth2 credentials
        if not self.config.client_id or not self.config.client_secret:
            raise ValueError(
                "OAuth2 authentication requires client_id and client_secret. "
                "Ensure AZURE_OPENAI_CLIENT_ID and AZURE_OPENAI_CLIENT_SECRET "
                "environment variables are set."
            )
        
        # Get fresh token
        logger.info("Refreshing OAuth2 token for Azure OpenAI")
        
        # OAuth2 token endpoint - support multiple tenant types
        if self.config.tenant_id == "common":
            # Cisco's setup uses id.cisco.com
            token_url = "https://id.cisco.com/oauth2/default/v1/token"
        else:
            # Standard Azure AD endpoint
            token_url = f"https://login.microsoftonline.com/{self.config.tenant_id}/oauth2/v2.0/token"
        
        # Prepare credentials (client_id:client_secret base64 encoded)
        credentials = f"{self.config.client_id}:{self.config.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_credentials}",
        }
        
        # Payload for token request
        if self.config.tenant_id == "common":
            # Cisco-style client credentials
            payload = "grant_type=client_credentials"
        else:
            # Azure AD with scope
            scope = f"api://{self.config.app_key}/.default" if self.config.app_key else "https://cognitiveservices.azure.com/.default"
            payload = f"grant_type=client_credentials&scope={scope}"
        
        try:
            logger.debug(f"Making OAuth2 token request to: {token_url}")
            
            # Make async request
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(token_url, headers=headers, data=payload, timeout=30)
            )
            response.raise_for_status()
            
            # Parse token response
            token_data = response.json()
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)
            
            if not access_token:
                raise ValueError("No access_token in OAuth2 response")
            
            # Cache the token
            self._cached_token = access_token
            self._token_expires_at = current_time + expires_in
            
            logger.info(f"Successfully obtained OAuth2 token (expires in {expires_in}s)")
            return access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"OAuth2 token request failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            raise RuntimeError(f"Failed to obtain OAuth2 token: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during OAuth2 token retrieval: {str(e)}")
            raise RuntimeError(f"OAuth2 authentication failed: {str(e)}")
    
    def invalidate_token(self):
        """Invalidate cached token to force refresh on next request."""
        logger.info("Invalidating cached OAuth2 token")
        self._cached_token = None
        self._token_expires_at = 0
    
    def is_token_valid(self) -> bool:
        """Check if current cached token is still valid."""
        if not self._cached_token:
            return False
        
        current_time = time.time()
        return current_time < (self._token_expires_at - self._token_buffer_seconds)


# Convenience function for backward compatibility
async def get_azure_token(client_id: str, client_secret: str, app_key: Optional[str] = None) -> str:
    """
    Backward compatibility function for direct Azure OpenAI token retrieval.
    
    Args:
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret  
        app_key: Optional application key
        
    Returns:
        Access token string
    """
    from ..core.schemas import LLMConfig
    
    # Create temporary LLMConfig for token retrieval
    config = LLMConfig(
        endpoint="https://temp.openai.azure.com/",  # Required but not used for token
        deployment="temp",  # Required but not used for token
        client_id=client_id,
        client_secret=client_secret,
        app_key=app_key
    )
    
    token_manager = LLMTokenManager(config)
    return await token_manager.get_token()