"""
AgentExecutor - AI Agent Node Execution

Implements AI agent execution using unified LangChain infrastructure with support for:
- Azure OpenAI with OAuth2 and API key authentication
- Multiple LLM providers (OpenAI, Anthropic, Ollama)
- Unified configuration via LLMConfig schema
- Shared client management and token handling

Author: AI Workflow Engine Team
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional

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
from ..core.schemas import WorkflowNode, AgentNodeConfig
from ..llm.client_factory import LLMClientFactory

# Set up structured logging
from ..shared.utils.logging import get_logger
logger = get_logger(__name__)

# Check for LangChain dependencies
try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.output_parsers import JsonOutputParser
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.error("LangChain dependencies required for agent execution. Install with: pip install langchain-core")


class AgentExecutor(NodeExecutor):
    """
    Executor for AI agent nodes using unified LangChain infrastructure.
    
    Supports multiple LLM providers via shared LLMConfig:
    - Azure OpenAI with OAuth2/API key authentication
    - OpenAI with API key authentication
    - Anthropic Claude with API key authentication
    - Ollama for local execution
    """

    NODE_TYPE = "agent"

    def __init__(self):
        super().__init__(default_timeout=120)

    async def execute_impl(self, node: WorkflowNode, context: ExecutionContext) -> ExecutionResult:
        """Execute AI agent node using unified LangChain infrastructure."""

        start_time = datetime.now(timezone.utc)

        try:
            # Parse and validate configuration using new schema
            config = AgentNodeConfig.model_validate(node.config)
            
            if not LANGCHAIN_AVAILABLE:
                raise RuntimeError(
                    "LangChain dependencies required for agent execution. "
                    "Install with: pip install langchain-core langchain-openai"
                )

            # Resolve prompt templates
            resolved_prompt = await context.resolve_template(config.prompt)
            
            resolved_system_prompt = None
            if config.system_prompt:
                resolved_system_prompt = await context.resolve_template(config.system_prompt)

            # Enhance prompts for JSON schema enforcement
            if config.response_format and config.response_format.get("type") == "json_schema":
                json_schema = config.response_format.get("json_schema", {})
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
            
            # Auto-generate schema instructions for json_object format
            elif config.response_format and config.response_format.get("type") == "json_object":
                schema_instructions = self._generate_schema_instructions_from_output_mapping(node)
                if schema_instructions:
                    resolved_prompt += schema_instructions
                    
                    logger.info(
                        "Enhanced prompt with auto-generated schema instructions from output_mapping",
                        node_id=node.id,
                        output_fields=list(getattr(node, 'output_mapping', {}).get('output_variables', {}).keys())
                    )

            logger.info(
                "Executing agent node with unified LLM infrastructure",
                node_id=node.id,
                provider=config.llm_config.provider,
                model=config.llm_config.model,
                prompt_length=len(resolved_prompt)
            )

            # Create LangChain client using shared infrastructure
            llm_client = await LLMClientFactory.create_langchain_client(config.llm_config)

            # Execute using LangChain
            response = await self._execute_with_langchain(
                llm_client, resolved_prompt, resolved_system_prompt, config
            )

            # Process response based on output format
            processed_response, context_updates = await self._process_response(
                response, node, config, resolved_prompt, resolved_system_prompt
            )

            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            metrics.network_calls = 1

            logger.info(
                "Agent execution completed successfully",
                node_id=node.id,
                provider=config.llm_config.provider,
                model=config.llm_config.model,
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
        config: AgentNodeConfig,
        resolved_prompt: str,
        resolved_system_prompt: Optional[str]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Process agent response based on output format (plain text vs structured JSON)
        
        Returns:
            tuple: (processed_response_data, context_updates)
        """
        
        # Check if JSON output is configured (either json_schema or json_object)
        response_format = config.response_format
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
                # Try to extract JSON from markdown code blocks first
                json_content = response.strip()
                
                # Check if response is wrapped in markdown code blocks
                if "```json" in json_content and "```" in json_content:
                    # Extract JSON from markdown code blocks
                    start_marker = "```json"
                    end_marker = "```"
                    start_idx = json_content.find(start_marker)
                    if start_idx != -1:
                        # Find the JSON content after the start marker
                        json_start = start_idx + len(start_marker)
                        end_idx = json_content.find(end_marker, json_start)
                        if end_idx != -1:
                            json_content = json_content[json_start:end_idx].strip()
                            logger.info(
                                "Extracted JSON from markdown code blocks",
                                node_id=node.id,
                                extracted_content=json_content[:100]
                            )
                
                parsed_response = json.loads(json_content)
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
                "model": config.llm_config.model,
                "provider": config.llm_config.provider,
                "prompt": resolved_prompt,
                "system_prompt": resolved_system_prompt,
                "output_format": "json",
                "node_name": node.name or node.config.get('name', node.id)  # Include node display name
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
                "model": config.llm_config.model,
                "provider": config.llm_config.provider,
                "prompt": resolved_prompt,
                "system_prompt": resolved_system_prompt,
                "output_format": "text",
                "node_name": node.name or node.config.get('name', node.id)  # Include node display name
            }
            
            # Context updates for plain text
            context_updates = {
                f"nodes.{node.id}.output": response,
                f"nodes.{node.id}.output.full": result_data
            }
            
            return result_data, context_updates

    async def _execute_with_langchain(
        self,
        llm_client: Any,
        prompt: str,
        system_prompt: Optional[str],
        config: AgentNodeConfig
    ) -> str:
        """Execute using pre-created LangChain client from shared infrastructure."""

        try:
            logger.info(
                "Executing with unified LangChain infrastructure",
                provider=config.llm_config.provider,
                model=config.llm_config.model
            )
            
            # Check for JSON schema and use JsonOutputParser if needed
            response_format = config.response_format
            if response_format and response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                if json_schema:
                    logger.info(
                        "Using LangChain JsonOutputParser for structured output",
                        schema_name=json_schema.get("name", "unknown"),
                        model=config.llm_config.model
                    )
                    
                    # Create JSON output parser
                    json_parser = JsonOutputParser()
                    
                    # Add JSON format instructions to prompt
                    enhanced_prompt = f"{prompt}\n\n{json_parser.get_format_instructions()}"
                    
                    # Try binding response_format and use parser chain
                    try:
                        client_with_format = llm_client.bind(response_format=response_format)
                        chain = client_with_format | json_parser
                    except Exception as bind_error:
                        logger.warning(
                            "Failed to bind response_format, using parser only",
                            error=str(bind_error)
                        )
                        chain = llm_client | json_parser
                    
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
                messages = []
                if system_prompt:
                    messages.append(SystemMessage(content=system_prompt))
                messages.append(HumanMessage(content=prompt))

                # Make the call
                response = await llm_client.ainvoke(messages)

            # Extract response content
            logger.info(
                "LangChain execution successful",
                provider=config.llm_config.provider,
                model=config.llm_config.model,
                response_length=len(str(response))
            )
            
            if hasattr(response, 'content'):
                return response.content
            else:
                return str(response)

        except Exception as e:
            logger.error(
                "LangChain execution failed",
                provider=config.llm_config.provider,
                model=config.llm_config.model,
                error=str(e)
            )
            raise RuntimeError(f"LangChain execution failed: {str(e)}")

    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate agent node configuration using unified LLMConfig."""
        result = ValidationResult(is_valid=True)

        try:
            # Validate using Pydantic schema (includes LLMConfig validation)
            AgentNodeConfig.model_validate(config)
            
        except Exception as e:
            result.add_error(
                f"Invalid agent configuration: {str(e)}",
                field="config",
                suggestion="Check LLM configuration, prompt, and other required fields"
            )
            return result

        # Check LangChain dependencies
        if not LANGCHAIN_AVAILABLE:
            result.add_error(
                "LangChain dependencies required for agent execution. "
                "Install with: pip install langchain-core langchain-openai",
                field="dependencies",
                suggestion="Install required LangChain packages"
            )

        # Additional validations - endpoint and deployment now auto-populate from environment

        # Validate timeout
        timeout_validation = validate_timeout_config(config)
        result = result.merge(timeout_validation)

        return result

    def _generate_schema_instructions_from_output_mapping(self, node: WorkflowNode) -> Optional[str]:
        """Generate JSON schema instructions from node output mapping for compatibility."""
        
        if not hasattr(node, 'output_mapping') or not node.output_mapping:
            return None
            
        output_vars = node.output_mapping.get('output_variables', {})
        if not output_vars:
            return None
        
        # Build JSON schema hint from output variables
        field_descriptions = []
        for var_name, var_config in output_vars.items():
            description = var_config.get('description', 'string value')
            field_descriptions.append(f'"{var_name}": "{description}"')
        
        schema_hint = f"\n\nIMPORTANT: Return a JSON object with these fields: {{{', '.join(field_descriptions)}}}"
        return schema_hint


# Test function for agent executor
async def test_agent_executor():
    """Test function for AgentExecutor"""
    from ..core.context import ExecutionContext
    
    # Create test context
    context = ExecutionContext("test_run")
    
    # Set up test data  
    await context.set("input.topic", "artificial intelligence")
    
    # Create agent executor
    executor = AgentExecutor()
    
    # Create test node with new schema
    test_node = WorkflowNode(
        id="test_agent_node",
        type="agent",
        name="Test Agent",
        config={
            "llm_config": {
                "provider": "azure_openai",
                "model": "gpt-4", 
                "endpoint": "https://your-endpoint.openai.azure.com/",
                "deployment": "gpt-4"
            },
            "prompt": "Write a brief summary about ${workflow.input.topic}",
            "system_prompt": "You are a helpful assistant.",
            "timeout": 60
        }
    )
    
    print("Testing unified agent executor...")
    print(f"Node: {test_node.id} ({test_node.type})")
    
    # Execute node
    result = await executor.execute(test_node, context)
    print(f"Status: {result.status.value}")
    print(f"Duration: {result.metrics.duration_ms}ms")
    print(f"Response: {result.data.get('response', 'No response') if result.data else 'No data'}")

    return result


if __name__ == "__main__":
    # Run test
    import asyncio
    asyncio.run(test_agent_executor())

