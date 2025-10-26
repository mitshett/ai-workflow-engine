"""
AgentExecutor - AI Agent Node Execution

Implements AI agent execution with support for Azure OpenAI integration,
including Cisco's internal Azure OpenAI setup with OAuth2 token authentication.

Author: AI Workflow Engine Team
"""

import asyncio
import base64
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import requests
import structlog

from ..core.node_executor import (
    NodeExecutor,
    ExecutionResult,
    ExecutionStatus,
    ExecutionMetrics,
    ValidationResult,
    validate_required_config,
    validate_timeout_config
)
from ..core.context import ExecutionContext
from ..core.schemas import WorkflowNode

# Set up structured logging
logger = structlog.get_logger(__name__)

# Check for optional LangChain dependencies
try:
    from langchain_openai import AzureChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.warning("LangChain dependencies not available. Agent execution will be limited.")

# Check for OpenAI direct client
try:
    from openai import AsyncOpenAI, AsyncAzureOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI client not available.")


class AzureOpenAITokenManager:
    """Manages Azure OpenAI token retrieval for Cisco's internal setup"""

    def __init__(self):
        self._cached_token = None
        self._token_expires_at = 0
        self._token_buffer_seconds = 300  # Refresh 5 minutes before expiry

    def get_client_details(self) -> tuple[str, str]:
        """Get client credentials from environment"""
        client_id = os.getenv("AZURE_OPENAI_CLIENT_ID")
        client_secret = os.getenv("AZURE_OPENAI_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise ValueError("Missing Azure OpenAI credentials: AZURE_OPENAI_CLIENT_ID, AZURE_OPENAI_CLIENT_SECRET")

        return client_id, client_secret

    async def get_token(self) -> str:
        """Retrieve Azure OpenAI access token with caching"""
        current_time = time.time()

        # Return cached token if still valid
        if (self._cached_token and
            current_time < (self._token_expires_at - self._token_buffer_seconds)):
            return self._cached_token

        # Get fresh token
        client_id, client_secret = self.get_client_details()

        # OAuth2 token endpoint
        token_url = "https://id.cisco.com/oauth2/default/v1/token"

        # Encode Client ID and Secret to Base64 for Basic Authorization header
        auth_key = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")

        # Headers for the token request
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_key}",
        }

        # Payload for the token request
        payload = "grant_type=client_credentials"

        try:
            # Make async request
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(token_url, headers=headers, data=payload, timeout=30)
            )
            response.raise_for_status()

        except requests.exceptions.RequestException as e:
            logger.error("Failed to retrieve Azure OpenAI token", error=str(e))
            raise RuntimeError(f"Failed to retrieve Azure OpenAI token: {str(e)}")

        # Parse the token from the response
        token_data = response.json()
        token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)  # Default 1 hour

        if not token:
            logger.error("Failed to retrieve access token from response")
            raise RuntimeError("Failed to retrieve access token from response")

        # Cache the token
        self._cached_token = token
        self._token_expires_at = current_time + expires_in

        logger.info("Successfully retrieved Azure OpenAI token", expires_in=expires_in)
        return token


class AgentExecutor(NodeExecutor):
    """
    Executor for AI agent nodes with Azure OpenAI integration.

    Supports both direct OpenAI client and LangChain integration
    with Cisco's internal Azure OpenAI setup.
    """

    NODE_TYPE = "agent"

    def __init__(self):
        super().__init__(default_timeout=120)
        self.token_manager = AzureOpenAITokenManager()
        self._langchain_clients = {}  # Cache LangChain clients
        self._openai_clients = {}     # Cache OpenAI clients

    async def execute_impl(self, node: WorkflowNode, context: ExecutionContext) -> ExecutionResult:
        """Execute AI agent node with Azure OpenAI integration"""

        start_time = datetime.now(timezone.utc)
        config = node.config

        try:
            # Get configuration
            provider = config.get("provider", "azure_openai")
            model = config.get("model", "gpt-35-turbo")
            use_langchain = config.get("use_langchain", True)

            # Resolve prompt template
            prompt_template = config.get("prompt", "")
            if not prompt_template:
                raise ValueError("Agent node must have a 'prompt' configuration")

            resolved_prompt = await context.resolve_template(prompt_template)

            # Get system prompt if provided
            system_prompt = config.get("system_prompt")
            if system_prompt:
                resolved_system_prompt = await context.resolve_template(system_prompt)
            else:
                resolved_system_prompt = None

            # Enhance prompts for JSON schema enforcement
            response_format = config.get("response_format")
            if response_format and response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                schema_structure = json_schema.get("schema", {})
                
                # Add JSON instruction to prompt
                json_instruction = "\n\nIMPORTANT: You must respond with a valid JSON object only. Do not include any text outside the JSON object."
                
                # Add schema hint if available
                if schema_structure.get("properties"):
                    properties = schema_structure["properties"]
                    required = schema_structure.get("required", [])
                    
                    prop_descriptions = []
                    for prop, details in properties.items():
                        required_marker = " (required)" if prop in required else ""
                        prop_descriptions.append(f'"{prop}": {details.get("description", "string value")}{required_marker}')
                    
                    schema_hint = f"\n\nReturn JSON with these fields: {{{', '.join(prop_descriptions)}}}"
                    json_instruction += schema_hint

                resolved_prompt += json_instruction
                
                logger.info(
                    "Enhanced prompt with JSON schema instructions",
                    node_id=node.id,
                    schema_name=json_schema.get("name", "unknown"),
                    required_fields=schema_structure.get("required", [])
                )
            
            # Auto-generate schema instructions for json_object format (Azure OpenAI compatible)
            elif response_format and response_format.get("type") == "json_object":
                schema_instructions = self._generate_schema_instructions_from_output_mapping(node)
                if schema_instructions:
                    resolved_prompt += schema_instructions
                    
                    logger.info(
                        "Enhanced prompt with auto-generated schema instructions from output_mapping",
                        node_id=node.id,
                        output_fields=list(getattr(node, 'output_mapping', {}).get('output_variables', {}).keys())
                    )

            logger.info(
                "Executing agent node",
                node_id=node.id,
                provider=provider,
                model=model,
                use_langchain=use_langchain,
                prompt_length=len(resolved_prompt)
            )

            # Execute based on provider and client type
            if provider == "azure_openai":
                if use_langchain and LANGCHAIN_AVAILABLE:
                    response = await self._execute_with_langchain(
                        model, resolved_prompt, resolved_system_prompt, config
                    )
                elif OPENAI_AVAILABLE:
                    response = await self._execute_with_openai_client(
                        model, resolved_prompt, resolved_system_prompt, config
                    )
                else:
                    raise RuntimeError("No available Azure OpenAI client libraries")
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            # Process response based on output format
            processed_response, context_updates = await self._process_response(
                response, node, config, resolved_prompt, resolved_system_prompt, provider, model
            )

            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            metrics.network_calls = 1

            logger.info(
                "Agent execution completed successfully",
                node_id=node.id,
                response_length=len(str(processed_response)) if processed_response else 0,
                duration_ms=metrics.duration_ms
            )

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                data=processed_response,
                metrics=metrics,
                context_updates=context_updates
            )

        except Exception as e:
            logger.error(
                "Agent execution failed",
                node_id=node.id,
                error=str(e),
                error_type=type(e).__name__
            )

            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()

            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                metrics=metrics
            )
            result.set_error(e, f"Agent execution failed for node {node.id}")
            return result

    async def _process_response(
        self, 
        response: str, 
        node: WorkflowNode, 
        config: Dict[str, Any],
        resolved_prompt: str,
        resolved_system_prompt: Optional[str],
        provider: str,
        model: str
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Process agent response based on output format (plain text vs structured JSON)
        
        Returns:
            tuple: (processed_response_data, context_updates)
        """
        
        # Check if JSON output is configured (either json_schema or json_object)
        response_format = config.get("response_format")
        json_schema_config = response_format.get("json_schema") if response_format else None
        is_json_output = response_format and response_format.get("type") in ["json_schema", "json_object"]
        
        if is_json_output:
            logger.info(
                "Processing structured JSON response",
                node_id=node.id,
                format_type=response_format.get("type"),
                schema_name=json_schema_config.get("name", "unknown") if json_schema_config else "json_object"
            )
            
            # Parse and validate JSON response
            try:
                parsed_response = json.loads(response.strip())
                logger.info(
                    "Successfully parsed JSON response",
                    node_id=node.id,
                    properties=list(parsed_response.keys()) if isinstance(parsed_response, dict) else "not_dict"
                )
            except json.JSONDecodeError as e:
                logger.error(
                    "Failed to parse JSON response", 
                    node_id=node.id, 
                    response=response[:200],
                    error=str(e)
                )
                # Fallback to plain text mode if JSON parsing fails
                parsed_response = {"response": response}
            
            # Prepare result data for structured output
            result_data = {
                "response": response,  # Keep original response
                "parsed": parsed_response,  # Parsed JSON data
                "model": model,
                "provider": provider,
                "prompt": resolved_prompt,
                "system_prompt": resolved_system_prompt,
                "output_format": "json"
            }
            
            # Create context updates with structured data mapping
            context_updates = {
                f"nodes.{node.id}.output": parsed_response,  # Main structured output
                f"nodes.{node.id}.output.full": result_data,  # Full result with metadata
                f"nodes.{node.id}.output.response": response  # Original text response
            }
            
            # Map individual JSON properties to workflow variables
            if isinstance(parsed_response, dict):
                for property_name, property_value in parsed_response.items():
                    context_updates[f"nodes.{node.id}.output.{property_name}"] = property_value
                    
                logger.info(
                    "Mapped JSON properties to workflow variables",
                    node_id=node.id,
                    properties=list(parsed_response.keys())
                )
            
            return result_data, context_updates
            
        else:
            logger.info(
                "Processing plain text response",
                node_id=node.id,
                response_length=len(response)
            )
            
            # Plain text output (original behavior)
            result_data = {
                "response": response,
                "model": model,
                "provider": provider,
                "prompt": resolved_prompt,
                "system_prompt": resolved_system_prompt,
                "output_format": "text"
            }
            
            # Context updates for plain text
            context_updates = {
                f"nodes.{node.id}.output": response,
                f"nodes.{node.id}.output.full": result_data
            }
            
            return result_data, context_updates

    async def _execute_with_langchain(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str],
        config: Dict[str, Any]
    ) -> str:
        """Execute using LangChain AzureChatOpenAI client"""

        retry_count = 0
        max_auth_retries = 2

        while retry_count <= max_auth_retries:
            try:
                logger.info(
                    "Attempting LangChain execution",
                    retry_count=retry_count,
                    max_auth_retries=max_auth_retries,
                    model=model
                )
                
                # Get or create LangChain client
                base_client = await self._get_langchain_client(model, config)
                
                # Check for JSON schema and use JsonOutputParser if needed
                response_format = config.get("response_format")
                if response_format and response_format.get("type") == "json_schema":
                    json_schema = response_format.get("json_schema", {})
                    if json_schema:
                        logger.info(
                            "Using LangChain JsonOutputParser for structured output",
                            schema_name=json_schema.get("name", "unknown"),
                            model=model
                        )
                        
                        # Create JSON output parser
                        json_parser = JsonOutputParser()
                        
                        # Add JSON format instructions to prompt
                        enhanced_prompt = f"{prompt}\n\n{json_parser.get_format_instructions()}"
                        
                        # Try binding response_format and use parser chain
                        try:
                            client_with_format = base_client.bind(response_format=response_format)
                            chain = client_with_format | json_parser
                        except Exception as bind_error:
                            logger.warning(
                                "Failed to bind response_format, using parser only",
                                error=str(bind_error)
                            )
                            chain = base_client | json_parser
                        
                        # Prepare messages with enhanced prompt
                        messages = []
                        if system_prompt:
                            messages.append(SystemMessage(content=system_prompt))
                        messages.append(HumanMessage(content=enhanced_prompt))
                        
                        # Make the call with JSON parser
                        response = await chain.ainvoke(messages)
                        
                        # JsonOutputParser returns parsed dict, convert back to string for consistency
                        if isinstance(response, dict):
                            response = json.dumps(response)
                        
                else:
                    # Regular text mode
                    client = base_client
                    
                    # Prepare messages
                    messages = []
                    if system_prompt:
                        messages.append(SystemMessage(content=system_prompt))
                    messages.append(HumanMessage(content=prompt))

                    # Make the call
                    response = await client.ainvoke(messages)

                # Extract response content
                logger.info(
                    "LangChain execution successful",
                    retry_count=retry_count,
                    response_length=len(str(response))
                )
                
                if hasattr(response, 'content'):
                    return response.content
                else:
                    return str(response)

            except Exception as e:
                error_str = str(e).lower()
                
                # Check if this is a 401 authentication error - broader detection
                is_auth_error = (
                    '401' in error_str or 
                    'unauthorized' in error_str or 
                    'token' in error_str or
                    'expired' in error_str or
                    'jwt' in error_str or
                    'authentication' in error_str
                )
                
                if is_auth_error and retry_count < max_auth_retries:
                    logger.warning(
                        "Authentication error detected, refreshing token and retrying",
                        error=str(e),
                        retry_count=retry_count
                    )
                    
                    # Invalidate cached client and token to force refresh
                    cache_key = f"langchain_{model}_{config.get('temperature', 0.7)}"
                    if cache_key in self._langchain_clients:
                        del self._langchain_clients[cache_key]
                    
                    # Force token refresh by clearing cache
                    self.token_manager._cached_token = None
                    self.token_manager._token_expires_at = 0
                    
                    retry_count += 1
                    continue
                else:
                    logger.error("LangChain execution failed", error=str(e), retry_count=retry_count)
                    raise RuntimeError(f"LangChain Azure OpenAI call failed: {str(e)}")

        raise RuntimeError("Maximum authentication retries exceeded")

    async def _execute_with_openai_client(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str],
        config: Dict[str, Any]
    ) -> str:
        """Execute using direct OpenAI client"""

        try:
            # Get or create OpenAI client
            client = await self._get_openai_client(config)

            # Prepare messages
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Prepare parameters
            params = {
                "model": model,
                "messages": messages,
                "temperature": config.get("temperature", 0.7),
                "max_tokens": config.get("max_tokens", 1000),
            }

            # Add JSON schema format if defined
            response_format = config.get("response_format")
            if response_format and response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                if json_schema:
                    logger.info(
                        "Adding JSON schema to OpenAI API call",
                        schema_name=json_schema.get("name", "unknown"),
                        model=model
                    )
                    params["response_format"] = response_format

            # Add user parameter for Cisco setup
            app_key = os.getenv("AZURE_OPENAI_APP_KEY")
            if app_key:
                params["user"] = json.dumps({"appkey": app_key})

            # Make the call
            response = await client.chat.completions.create(**params)

            # Extract response
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            else:
                raise RuntimeError("No response content received from Azure OpenAI")

        except Exception as e:
            logger.error("Direct OpenAI client execution failed", error=str(e))
            raise RuntimeError(f"Azure OpenAI API call failed: {str(e)}")

    async def _get_langchain_client(self, model: str, config: Dict[str, Any]) -> Any:
        """Get or create cached LangChain client"""

        cache_key = f"langchain_{model}_{config.get('temperature', 0.7)}"

        if cache_key in self._langchain_clients:
            return self._langchain_clients[cache_key]

        # Get token
        token = await self.token_manager.get_token()

        # Azure OpenAI configuration
        api_version = os.getenv("API_VERSION", "2024-08-01-preview")
        llm_endpoint = os.getenv("LLM_ENDPOINT", "https://chat-ai.cisco.com")
        app_key = os.getenv("AZURE_OPENAI_APP_KEY")

        if not app_key:
            raise ValueError("Missing environment variable: AZURE_OPENAI_APP_KEY")

        user_param = json.dumps({"appkey": app_key})

        # Create LangChain Azure OpenAI client
        client = AzureChatOpenAI(
            deployment_name=model,
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 1000),
            azure_endpoint=llm_endpoint,
            api_key=token,
            api_version=api_version,
            user=user_param,
            verbose=config.get("verbose", False)
        )

        # Cache the client
        self._langchain_clients[cache_key] = client

        logger.info("Created LangChain Azure OpenAI client", model=model, cache_key=cache_key)
        return client

    async def _get_openai_client(self, config: Dict[str, Any]) -> Any:
        """Get or create cached OpenAI client"""

        cache_key = "azure_openai_client"

        if cache_key in self._openai_clients:
            # Update token for existing client
            token = await self.token_manager.get_token()
            self._openai_clients[cache_key].api_key = token
            return self._openai_clients[cache_key]

        # Get token
        token = await self.token_manager.get_token()

        # Azure OpenAI configuration
        api_version = os.getenv("API_VERSION", "2024-08-01-preview")
        llm_endpoint = os.getenv("LLM_ENDPOINT", "https://chat-ai.cisco.com")

        # Create Azure OpenAI client
        client = AsyncAzureOpenAI(
            api_key=token,
            api_version=api_version,
            azure_endpoint=llm_endpoint
        )

        # Cache the client
        self._openai_clients[cache_key] = client

        logger.info("Created direct Azure OpenAI client", cache_key=cache_key)
        return client

    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate agent node configuration"""
        result = ValidationResult(is_valid=True)

        # Check required fields
        required_validation = validate_required_config(config, ["prompt"])
        result = result.merge(required_validation)

        # Validate provider
        provider = config.get("provider", "azure_openai")
        if provider not in ["azure_openai"]:
            result.add_error(
                f"Unsupported provider: {provider}",
                field="provider",
                suggestion="Use 'azure_openai' for Cisco's Azure OpenAI setup"
            )

        # Validate model
        model = config.get("model", "gpt-35-turbo")
        supported_models = ["gpt-35-turbo", "gpt-4", "gpt-4-32k"]
        if model not in supported_models:
            result.add_warning(
                f"Model '{model}' may not be supported",
                field="model",
                suggestion=f"Consider using one of: {', '.join(supported_models)}"
            )

        # Validate temperature
        temperature = config.get("temperature")
        if temperature is not None:
            if not isinstance(temperature, (int, float)):
                result.add_error("Temperature must be a number", field="temperature")
            elif temperature < 0 or temperature > 2:
                result.add_error(
                    "Temperature must be between 0 and 2",
                    field="temperature",
                    suggestion="Use 0 for deterministic, 1 for balanced, 2 for creative"
                )

        # Validate max_tokens
        max_tokens = config.get("max_tokens")
        if max_tokens is not None:
            if not isinstance(max_tokens, int):
                result.add_error("max_tokens must be an integer", field="max_tokens")
            elif max_tokens <= 0:
                result.add_error("max_tokens must be positive", field="max_tokens")
            elif max_tokens > 32000:
                result.add_warning(
                    "max_tokens is very high and may cause timeouts",
                    field="max_tokens"
                )

        # Validate timeout
        timeout_validation = validate_timeout_config(config)
        result = result.merge(timeout_validation)

        # Validate response_format if present
        response_format = config.get("response_format")
        if response_format:
            if not isinstance(response_format, dict):
                result.add_error("response_format must be a dictionary", field="response_format")
            else:
                format_type = response_format.get("type")
                if format_type == "json_schema":
                    json_schema = response_format.get("json_schema")
                    if not json_schema:
                        result.add_error(
                            "json_schema must be provided when type is 'json_schema'", 
                            field="response_format.json_schema"
                        )
                    elif not isinstance(json_schema, dict):
                        result.add_error(
                            "json_schema must be a dictionary", 
                            field="response_format.json_schema"
                        )
                    else:
                        # Validate JSON schema structure
                        schema = json_schema.get("schema")
                        if not schema:
                            result.add_error(
                                "json_schema must contain a 'schema' field",
                                field="response_format.json_schema.schema"
                            )
                        elif not isinstance(schema, dict):
                            result.add_error(
                                "json_schema.schema must be a dictionary",
                                field="response_format.json_schema.schema"
                            )
                elif format_type and format_type != "text":
                    result.add_warning(
                        f"Unknown response_format type: {format_type}",
                        field="response_format.type",
                        suggestion="Use 'json_schema' for structured output or omit for plain text"
                    )

        # Check environment variables
        required_env_vars = [
            "AZURE_OPENAI_CLIENT_ID",
            "AZURE_OPENAI_CLIENT_SECRET",
            "AZURE_OPENAI_APP_KEY"
        ]

        missing_env_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_env_vars:
            result.add_error(
                f"Missing required environment variables: {', '.join(missing_env_vars)}",
                suggestion="Set Azure OpenAI credentials in environment"
            )

        return result

    def get_retry_policy(self):
        """Get retry policy for agent execution"""
        from ..core.node_executor import RetryPolicy

        return RetryPolicy(
            max_attempts=3,
            base_delay_seconds=2.0,
            exponential_backoff=True,
            retry_on_timeout=True,
            retry_on_network_error=True,
            retry_on_rate_limit=True,
            retry_on_server_error=True,
            retry_on_authentication_error=True,  # Retry auth errors (token refresh)
            retry_on_validation_error=False
        )

    def _generate_schema_instructions_from_output_mapping(self, node: WorkflowNode) -> Optional[str]:
        """
        Generate JSON schema instructions from workflow node's output_mapping configuration.
        This provides schema enforcement for json_object format (Azure OpenAI compatible).
        
        Args:
            node: Workflow node with potential output_mapping
            
        Returns:
            Schema instruction string or None if no output mapping found
        """
        output_mapping = getattr(node, 'output_mapping', None) or node.config.get('output_mapping')
        if not output_mapping:
            return None
            
        output_variables = output_mapping.get('output_variables', {})
        if not output_variables:
            return None
            
        # Build field descriptions from output variables
        field_descriptions = []
        for field_name, field_config in output_variables.items():
            field_type = field_config.get('type', 'string')
            description = field_config.get('description', f'{field_type} value')
            field_descriptions.append(f'  "{field_name}": "{description}"')
        
        if not field_descriptions:
            return None
            
        schema_instruction = (
            f"\n\nIMPORTANT: You must respond with a valid JSON object containing exactly these fields as top-level properties:\n"
            f"{{\n{chr(10).join(field_descriptions)}\n}}\n"
            f"Do not nest these fields under other objects. Do not include any text outside the JSON object."
        )
        
        return schema_instruction


# Convenience function for testing
async def test_agent_executor():
    """Test function for AgentExecutor"""
    from unittest.mock import AsyncMock
    from ..core.context import ExecutionContext

    # Create mock context
    mock_session = AsyncMock()
    context = ExecutionContext("test_run", mock_session)

    # Set up test data
    await context.set("workflow.input.user_name", "Alice")
    await context.set("workflow.input.task", "write a poem")

    # Create agent executor
    executor = AgentExecutor()

    # Create test node
    test_node = WorkflowNode(
        id="test_agent",
        type="agent",
        config={
            "provider": "azure_openai",
            "model": "gpt-35-turbo",
            "prompt": "Hello ${workflow.input.user_name}, please ${workflow.input.task}",
            "system_prompt": "You are a helpful AI assistant.",
            "temperature": 0.7,
            "max_tokens": 500
        },
        next=[]
    )

    # Execute
    result = await executor.execute(test_node, context)

    print(f"Execution Status: {result.status}")
    print(f"Response: {result.data.get('response', 'No response') if result.data else 'No data'}")

    return result


if __name__ == "__main__":
    # Run test
    asyncio.run(test_agent_executor())