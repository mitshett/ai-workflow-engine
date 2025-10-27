"""
AI provider enumerations for the AI Workflow Engine.

This module defines the supported AI providers and their configurations.

Author: AI Workflow Engine Team
"""

from enum import Enum


class AIProviderType(str, Enum):
    """
    Enumeration of supported AI providers.
    
    These providers can be used by agent nodes to generate AI responses.
    """
    
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    AZURE_OPENAI = "azure_openai"
    
    @property
    def requires_api_key(self) -> bool:
        """Check if this provider requires an API key."""
        return True  # All current providers require API keys
    
    @property
    def supports_streaming(self) -> bool:
        """Check if this provider supports streaming responses."""
        return self in (
            AIProviderType.OPENAI,
            AIProviderType.ANTHROPIC,
            AIProviderType.AZURE_OPENAI
        )
    
    @property
    def supports_function_calling(self) -> bool:
        """Check if this provider supports function calling."""
        return self in (
            AIProviderType.OPENAI,
            AIProviderType.AZURE_OPENAI
        )
    
    @property
    def default_models(self) -> list:
        """Get list of default models for this provider."""
        model_mappings = {
            AIProviderType.OPENAI: [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-3.5-turbo"
            ],
            AIProviderType.ANTHROPIC: [
                "claude-3-5-sonnet-20241022",
                "claude-3-haiku-20240307",
                "claude-3-opus-20240229"
            ],
            AIProviderType.AZURE_OPENAI: [
                "gpt-4o",
                "gpt-4",
                "gpt-35-turbo"
            ],
            AIProviderType.AZURE: [
                "gpt-4",
                "gpt-35-turbo"
            ]
        }
        return model_mappings.get(self, [])


class ResponseFormat(str, Enum):
    """
    Enumeration of supported AI response formats.
    
    These formats determine how AI providers should structure their responses.
    """
    
    TEXT = "text"
    JSON = "json"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"
    
    @property
    def is_structured(self) -> bool:
        """Check if this format produces structured output."""
        return self in (
            ResponseFormat.JSON,
            ResponseFormat.JSON_OBJECT,
            ResponseFormat.JSON_SCHEMA
        )
    
    @property
    def requires_schema(self) -> bool:
        """Check if this format requires a schema definition."""
        return self == ResponseFormat.JSON_SCHEMA