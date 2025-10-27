"""
MCPToolExecutor - MCP Tool Node Execution

Implements MCP (Model Context Protocol) tool execution with support for
HTTP and stdio MCP servers, connection pooling, and template resolution.

Author: AI Workflow Engine Team
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List


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
from ..core.schemas import WorkflowNode, MCPToolNodeConfig, MCPServerConfig
from ..mcp.client_manager import MCPClientManager, MCPError

# Set up structured logging
from ..shared.utils.logging import get_logger
logger = get_logger(__name__)


class MCPToolExecutor(NodeExecutor):
    """
    Executor for MCP tool nodes with connection pooling and template support.
    
    Supports both HTTP and stdio MCP servers with automatic connection
    management, template variable resolution, and comprehensive error handling.
    """
    
    NODE_TYPE = "mcp_tool"
    
    def __init__(self, client_manager: Optional[MCPClientManager] = None):
        super().__init__(default_timeout=300)  # 5 minute default for MCP tools
        self.client_manager = client_manager or MCPClientManager()
    
    async def execute_impl(self, node: WorkflowNode, context: ExecutionContext) -> ExecutionResult:
        """Execute MCP tool node with connection pooling and template resolution."""
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Parse and validate configuration
            config = MCPToolNodeConfig.model_validate(node.config)
            
            # Resolve template variables in tool arguments
            resolved_args = await self._resolve_template_arguments(
                config.tool_arguments, context
            )
            
            logger.info(
                "Executing MCP tool node",
                node_id=node.id,
                server_type=config.server.type,
                server_url=config.server.url or config.server.command,
                tool_name=config.tool_name,
                resolved_args=resolved_args
            )
            
            # Execute tool via MCP client manager
            result = await self.client_manager.call_tool(
                config.server,
                config.tool_name,
                resolved_args
            )
            
            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            metrics.network_calls = 1
            
            # Process response based on output format and content
            processed_result, context_updates = await self._process_response(
                result, node, config, config.tool_name, resolved_args
            )
            
            logger.info(
                "MCP tool execution completed successfully",
                node_id=node.id,
                tool_name=config.tool_name,
                duration_ms=metrics.duration_ms,
                result_keys=list(result.keys()) if isinstance(result, dict) else None
            )
            
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                data=processed_result,
                metrics=metrics,
                context_updates=context_updates
            )
            
        except MCPError as e:
            logger.error(
                "MCP tool execution failed",
                node_id=node.id,
                error=str(e),
                mcp_error_code=getattr(e, 'code', None)
            )
            
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            metrics.error_count = 1
            
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                metrics=metrics
            )
            result.set_error(e, f"MCP tool execution failed for node {node.id}")
            return result
            
        except Exception as e:
            logger.error(
                "MCP tool execution failed with unexpected error",
                node_id=node.id,
                error=str(e),
                error_type=type(e).__name__
            )
            
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            metrics.error_count = 1
            
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                metrics=metrics
            )
            result.set_error(e, f"MCP tool execution failed for node {node.id}")
            return result

    async def _process_response(
        self,
        result: Any,
        node: WorkflowNode,
        config: Any,
        tool_name: str,
        resolved_args: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Process MCP tool response based on output format (plain text vs structured JSON).
        
        Args:
            result: Raw result from MCP tool
            node: WorkflowNode instance
            config: Node configuration
            tool_name: Name of the MCP tool
            resolved_args: Resolved tool arguments
            
        Returns:
            tuple: (processed_result_data, context_updates)
        """
        
        # Check if output_format is configured for JSON processing
        output_format = getattr(config, 'output_format', None) or 'auto'
        
        # Try to detect if result contains JSON content
        json_content = None
        is_json_output = False
        
        if output_format in ['json', 'json_object']:
            is_json_output = True
        elif output_format == 'auto':
            # Auto-detect JSON in result
            if isinstance(result, dict):
                # Result is already a dictionary
                json_content = result
                is_json_output = True
            elif isinstance(result, str):
                # Try to parse string as JSON
                try:
                    json_content = json.loads(result.strip())
                    is_json_output = True
                except (json.JSONDecodeError, AttributeError):
                    is_json_output = False
            elif hasattr(result, 'get') and isinstance(result.get('content'), str):
                # Handle MCP tool response format: {"content": "json_string"}
                try:
                    json_content = json.loads(result.get('content', '').strip())
                    is_json_output = True
                except (json.JSONDecodeError, AttributeError):
                    is_json_output = False
        
        if is_json_output and json_content is not None:
            logger.info(
                "Processing structured JSON response from MCP tool",
                node_id=node.id,
                tool_name=tool_name,
                json_keys=list(json_content.keys()) if isinstance(json_content, dict) else "not_dict"
            )
            
            # Prepare result data for structured output
            result_data = {
                "tool_result": result,
                "parsed": json_content,
                "tool_name": tool_name,
                "server_type": getattr(config.server, 'type', 'unknown'),
                "server_url": getattr(config.server, 'url', None) or getattr(config.server, 'command', None),
                "resolved_arguments": resolved_args,
                "output_format": "json"
            }
            
            # Create context updates with structured data mapping
            context_updates = {
                f"nodes.{node.id}.output": json_content,  # Main structured output
                f"nodes.{node.id}.output.full": result_data,  # Full result with metadata
                f"nodes.{node.id}.tool_name": tool_name,
                f"nodes.{node.id}.success": result.get("success", True) if isinstance(result, dict) else True
            }
            
            # Map individual JSON properties to workflow variables
            if isinstance(json_content, dict):
                for property_name, property_value in json_content.items():
                    context_updates[f"nodes.{node.id}.output.{property_name}"] = property_value
                    # Also add direct access (backwards compatibility)
                    context_updates[f"nodes.{node.id}.{property_name}"] = property_value
                
                logger.info(
                    "Mapped JSON properties to workflow variables",
                    node_id=node.id,
                    tool_name=tool_name,
                    properties=list(json_content.keys())
                )
            
            return result_data, context_updates
            
        else:
            logger.info(
                "Processing plain text response from MCP tool",
                node_id=node.id,
                tool_name=tool_name,
                result_type=type(result).__name__
            )
            
            # Plain text/object output (original behavior)
            result_data = {
                "tool_result": result,
                "tool_name": tool_name,
                "server_type": getattr(config.server, 'type', 'unknown'),
                "server_url": getattr(config.server, 'url', None) or getattr(config.server, 'command', None),
                "resolved_arguments": resolved_args,
                "output_format": "text"
            }
            
            # Context updates for plain text/object
            context_updates = {
                f"nodes.{node.id}.output": result,
                f"nodes.{node.id}.output.full": result_data,
                f"nodes.{node.id}.tool_name": tool_name,
                f"nodes.{node.id}.success": result.get("success", True) if isinstance(result, dict) else True
            }
            
            # Add individual result fields for easy template access (backwards compatibility)
            if isinstance(result, dict):
                for key, value in result.items():
                    context_updates[f"nodes.{node.id}.{key}"] = value
            
            return result_data, context_updates
    
    async def _resolve_template_arguments(
        self, 
        arguments: Dict[str, Any], 
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """Resolve template variables in MCP tool arguments.
        
        Supports template syntax like:
        - {{input.product_id}} -> context.get("input.product_id")
        - {{nodes.node1.output.version}} -> context.get("nodes.node1.output.version")
        - {{workflow.run_id}} -> context.get("workflow.run_id")
        """
        resolved = {}
        
        for key, value in arguments.items():
            if isinstance(value, str):
                resolved_value = await self._resolve_template_string(value, context)
                resolved[key] = resolved_value
            elif isinstance(value, dict):
                # Recursively resolve nested dictionaries
                resolved[key] = await self._resolve_template_arguments(value, context)
            elif isinstance(value, list):
                # Resolve template strings in lists
                resolved_list = []
                for item in value:
                    if isinstance(item, str):
                        resolved_item = await self._resolve_template_string(item, context)
                        resolved_list.append(resolved_item)
                    else:
                        resolved_list.append(item)
                resolved[key] = resolved_list
            else:
                # Non-string values pass through unchanged
                resolved[key] = value
        
        return resolved
    
    async def _resolve_template_string(self, template_str: str, context: ExecutionContext) -> Any:
        """Resolve template variables in a string."""
        
        # Pattern to match {{variable.path}} syntax
        template_pattern = r'\{\{([^}]+)\}\}'
        
        def replace_template(match):
            var_path = match.group(1).strip()
            
            try:
                # Get value from context using dot notation
                value = context.get_sync(var_path)
                
                # Convert to string for substitution
                if value is None:
                    logger.warning(
                        "Template variable not found in context",
                        variable=var_path,
                        available_keys=list(context.data.keys())
                    )
                    return f"{{{{ {var_path} }}}}"  # Leave unresolved if not found
                
                return str(value)
                
            except Exception as e:
                logger.warning(
                    "Failed to resolve template variable",
                    variable=var_path,
                    error=str(e)
                )
                return f"{{{{ {var_path} }}}}"  # Leave unresolved on error
        
        # Check if entire string is a single template variable
        full_match = re.match(r'^\{\{([^}]+)\}\}$', template_str.strip())
        if full_match:
            # Return the actual value type, not string conversion
            var_path = full_match.group(1).strip()
            try:
                value = context.get_sync(var_path)
                return value if value is not None else template_str
            except Exception:
                return template_str
        
        # Replace template variables in string
        resolved_str = re.sub(template_pattern, replace_template, template_str)
        return resolved_str
    
    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate MCP tool node configuration."""
        result = ValidationResult(is_valid=True)
        
        try:
            # Validate using Pydantic schema
            MCPToolNodeConfig.model_validate(config)
            
        except Exception as e:
            result.add_error(
                f"Invalid MCP tool configuration: {str(e)}",
                field="config",
                suggestion="Check server configuration and tool_name"
            )
            return result
        
        # Additional validation
        server_config = config.get("server", {})
        server_type = server_config.get("type", "http")
        
        if server_type == "http":
            url = server_config.get("url")
            if not url:
                result.add_error(
                    "HTTP MCP server requires 'url' field",
                    field="server.url",
                    suggestion="Provide the HTTP URL of the MCP server"
                )
            elif not url.startswith(("http://", "https://")):
                result.add_error(
                    "MCP server URL must be a valid HTTP/HTTPS URL",
                    field="server.url"
                )
        
        elif server_type == "stdio":
            command = server_config.get("command")
            if not command:
                result.add_error(
                    "Stdio MCP server requires 'command' field",
                    field="server.command",
                    suggestion="Provide the command to start the MCP server"
                )
            else:
                result.add_warning(
                    "Stdio MCP servers are not yet fully implemented",
                    field="server.type"
                )
        
        # Validate tool name
        tool_name = config.get("tool_name")
        if not tool_name:
            result.add_error(
                "MCP tool node requires 'tool_name'",
                field="tool_name",
                suggestion="Specify which tool to call on the MCP server"
            )
        
        # Validate timeout
        timeout_validation = validate_timeout_config(config)
        result = result.merge(timeout_validation)
        
        return result
    
    def get_retry_policy(self):
        """Get retry policy for MCP tool execution."""
        from ..core.node_executor import RetryPolicy
        
        return RetryPolicy(
            max_attempts=3,
            base_delay_seconds=2.0,
            exponential_backoff=True,
            retry_on_timeout=True,
            retry_on_network_error=True,
            retry_on_rate_limit=False,  # MCP servers typically don't have rate limits
            retry_on_server_error=True,
            retry_on_authentication_error=False,  # MCP doesn't typically use auth
            retry_on_validation_error=False
        )
    
    async def discover_server_tools(self, server_config: MCPServerConfig) -> List[Dict[str, Any]]:
        """Discover available tools from an MCP server.
        
        This is a utility method for the designer UI to discover available tools.
        """
        try:
            tools = await self.client_manager.list_server_tools(server_config)
            logger.info(
                "Successfully discovered MCP server tools",
                server_type=server_config.type,
                server_url=server_config.url or server_config.command,
                tool_count=len(tools)
            )
            return tools
        except Exception as e:
            logger.error(
                "Failed to discover MCP server tools",
                server_type=server_config.type,
                server_url=server_config.url or server_config.command,
                error=str(e)
            )
            raise MCPError(f"Tool discovery failed: {str(e)}")
    
    async def cleanup(self):
        """Clean up MCP client connections."""
        if self.client_manager:
            await self.client_manager.disconnect_all()


# Convenience function for testing
async def test_mcp_executor():
    """Test function for MCPToolExecutor"""
    from unittest.mock import AsyncMock
    from ..core.context import ExecutionContext
    
    # Create mock context
    mock_session = AsyncMock()
    context = ExecutionContext("test_run")
    
    # Set up test data
    await context.set("input.product_id", "WS-C3850-24T-E")
    await context.set("input.os_type", "iosxe")
    await context.set("input.version", "17.3.4")
    
    # Create MCP executor
    executor = MCPToolExecutor()
    
    # Create test node
    test_node = WorkflowNode(
        id="test_mcp_tool",
        type="mcp_tool",
        config={
            "server": {
                "type": "http",
                "url": "http://localhost:8080",
                "timeout": 30
            },
            "tool_name": "get_security_advisories",
            "tool_arguments": {
                "os_type": "{{input.os_type}}",
                "version": "{{input.version}}"
            },
            "timeout": 300
        },
        next=[]
    )
    
    # Execute
    result = await executor.execute(test_node, context)
    
    print(f"Execution Status: {result.status}")
    print(f"Tool Result: {result.data.get('tool_result', 'No result') if result.data else 'No data'}")
    
    # Cleanup
    await executor.cleanup()
    
    return result


if __name__ == "__main__":
    # Run test
    asyncio.run(test_mcp_executor())