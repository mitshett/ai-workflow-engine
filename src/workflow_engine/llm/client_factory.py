"""
LLM Client Factory

Unified LangChain client creation for all LLM providers supporting:
- LangChain clients (AzureChatOpenAI, ChatOpenAI, ChatAnthropic)
- Connection pooling and caching with automatic token refresh
- Automatic authentication handling
"""

import json
from typing import Any, Dict, Optional
from ..core.schemas import LLMConfig
from .token_manager import LLMTokenManager
from ..shared.utils.logging import get_logger

logger = get_logger(__name__)

# Optional imports - handle missing dependencies gracefully
try:
    from langchain_openai import AzureChatOpenAI, ChatOpenAI
    LANGCHAIN_OPENAI_AVAILABLE = True
except ImportError:
    AzureChatOpenAI = None  # Define as None to avoid NameError in type annotations
    ChatOpenAI = None
    LANGCHAIN_OPENAI_AVAILABLE = False
    logger.warning("langchain-openai not available")

# Anthropic support removed to resolve version conflicts with MCP adapters
ChatAnthropic = None
LANGCHAIN_ANTHROPIC_AVAILABLE = False


class LLMClientFactory:
    """Factory for creating LangChain clients with automatic authentication and token refresh."""
    
    _langchain_clients: Dict[str, Any] = {}
    _token_managers: Dict[str, LLMTokenManager] = {}
    
    @classmethod
    async def create_langchain_client(cls, llm_config: LLMConfig) -> Any:
        """
        Create LangChain client for the specified LLM configuration.
        
        Args:
            llm_config: LLM configuration
            
        Returns:
            LangChain client (AzureChatOpenAI, ChatOpenAI, ChatAnthropic, etc.)
        """
        
        # Create cache key
        cache_key = cls._get_cache_key(llm_config, "langchain")
        
        # Return cached client if available, but refresh token if needed
        if cache_key in cls._langchain_clients:
            client = cls._langchain_clients[cache_key]
            
            # Update token for existing LangChain client if needed (Azure only)
            if llm_config.provider == "azure_openai":
                token_manager = cls._get_token_manager(llm_config)
                fresh_token = await token_manager.get_token()
                
                # Update the LangChain client's api_key
                if hasattr(client, 'api_key'):
                    client.api_key = fresh_token
                elif hasattr(client, 'openai_api_key'):
                    client.openai_api_key = fresh_token
                else:
                    # If we can't update token, recreate client
                    logger.warning("Cannot update token on cached LangChain client, recreating...")
                    del cls._langchain_clients[cache_key]
                    return await cls.create_langchain_client(llm_config)
                
                logger.debug("Updated token on cached LangChain client")
            
            return client
        
        logger.info(f"Creating LangChain client for provider: {llm_config.provider}")
        
        if llm_config.provider == "azure_openai":
            if not LANGCHAIN_OPENAI_AVAILABLE:
                raise ImportError("langchain-openai required for Azure OpenAI. Install with: pip install langchain-openai")
            
            client = await cls._create_azure_langchain_client(llm_config)
            
        elif llm_config.provider == "openai":
            if not LANGCHAIN_OPENAI_AVAILABLE:
                raise ImportError("langchain-openai required for OpenAI. Install with: pip install langchain-openai")
            
            client = await cls._create_openai_langchain_client(llm_config)
            
        else:
            raise ValueError(f"Unsupported LLM provider for LangChain: {llm_config.provider}")
        
        # Cache the client
        cls._langchain_clients[cache_key] = client
        logger.info(f"Created and cached LangChain client: {cache_key}")
        
        return client
    
    
    @classmethod
    async def _create_azure_langchain_client(cls, llm_config: LLMConfig) -> AzureChatOpenAI:
        """Create Azure OpenAI LangChain client."""
        
        # Get authentication token
        token_manager = cls._get_token_manager(llm_config)
        token = await token_manager.get_token()
        
        # Prepare user parameter for corporate setups
        user_param = None
        if llm_config.app_key:
            user_param = json.dumps({"appkey": llm_config.app_key})
        
        # Create LangChain Azure OpenAI client
        client_params = {
            "deployment_name": llm_config.deployment,
            "model": llm_config.model,
            "temperature": llm_config.temperature,
            "azure_endpoint": llm_config.endpoint,
            "api_version": llm_config.api_version,
            "api_key": token,
            "timeout": 60,
            "max_retries": 3
        }
        
        if llm_config.max_tokens is not None:
            client_params["max_tokens"] = llm_config.max_tokens
        
        if user_param:
            client_params["user"] = user_param
            
        client = AzureChatOpenAI(**client_params)
        
        logger.info(f"Created Azure LangChain client - endpoint: {llm_config.endpoint}, deployment: {llm_config.deployment}")
        return client
    
    @classmethod
    async def _create_openai_langchain_client(cls, llm_config: LLMConfig) -> ChatOpenAI:
        """Create OpenAI LangChain client."""
        
        client_params = {
            "model": llm_config.model,
            "temperature": llm_config.temperature,
            "api_key": llm_config.api_key,
            "timeout": 60,
            "max_retries": 3
        }
        
        if llm_config.max_tokens is not None:
            client_params["max_tokens"] = llm_config.max_tokens
        
        client = ChatOpenAI(**client_params)
        
        logger.info(f"Created OpenAI LangChain client - model: {llm_config.model}")
        return client
    
    
    @classmethod
    def _get_token_manager(cls, llm_config: LLMConfig) -> LLMTokenManager:
        """Get or create token manager for the LLM configuration."""
        
        # Create cache key for token manager
        token_key = f"{llm_config.provider}:{llm_config.client_id or 'api_key'}"
        
        if token_key not in cls._token_managers:
            cls._token_managers[token_key] = LLMTokenManager(llm_config)
        
        return cls._token_managers[token_key]
    
    @classmethod
    def _get_cache_key(cls, llm_config: LLMConfig, client_type: str) -> str:
        """Generate cache key for client caching."""
        
        key_parts = [
            client_type,
            llm_config.provider,
            llm_config.model,
            str(llm_config.temperature),
            str(llm_config.max_tokens)
        ]
        
        if llm_config.provider == "azure_openai":
            key_parts.extend([
                llm_config.endpoint,
                llm_config.deployment,
                llm_config.client_id or "api_key"
            ])
        
        return ":".join(key_parts)
    
    @classmethod
    def invalidate_cache(cls, llm_config: Optional[LLMConfig] = None):
        """
        Invalidate cached clients and token managers.
        
        Args:
            llm_config: If provided, invalidate only for this config. Otherwise, clear all.
        """
        
        if llm_config:
            # Invalidate specific configuration
            langchain_key = cls._get_cache_key(llm_config, "langchain")
            token_key = f"{llm_config.provider}:{llm_config.client_id or 'api_key'}"
            
            cls._langchain_clients.pop(langchain_key, None)
            
            if token_key in cls._token_managers:
                cls._token_managers[token_key].invalidate_token()
                
            logger.info(f"Invalidated cache for {llm_config.provider} configuration")
            
        else:
            # Clear all caches
            cls._langchain_clients.clear()
            
            for token_manager in cls._token_managers.values():
                token_manager.invalidate_token()
            cls._token_managers.clear()
            
            logger.info("Cleared all client caches")


# Convenience functions
async def get_langchain_client(llm_config: LLMConfig) -> Any:
    """Convenience function to get LangChain client."""
    return await LLMClientFactory.create_langchain_client(llm_config)