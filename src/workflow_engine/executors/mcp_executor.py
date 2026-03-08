"""
MCPToolExecutor - Smart MCP Tool Node Execution

Implements smart MCP (Model Context Protocol) tool execution with support for:
- LLM-based tool discovery and selection
- Natural language task descriptions
- HTTP and stdio MCP servers, connection pooling, and template resolution
- Fallback to direct tool execution

Author: AI Workflow Engine Team
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from openai import AuthenticationError as OpenAIAuthError


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
from ..llm.client_factory import LLMClientFactory

# Set up structured logging
from ..shared.utils.logging import get_logger
logger = get_logger(__name__)

# Optional LangChain MCP imports - handle missing dependencies gracefully
try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.graph import StateGraph, MessagesState, START
    from langgraph.prebuilt import ToolNode, tools_condition
    from langchain_core.messages import HumanMessage, SystemMessage
    LANGCHAIN_MCP_AVAILABLE = True
except ImportError:
    LANGCHAIN_MCP_AVAILABLE = False
    logger.warning("LangChain MCP dependencies not available. Smart MCP execution will be disabled.")


class MCPToolExecutor(NodeExecutor):
    """
    Smart executor for MCP tool nodes with LLM-based tool discovery.
    
    Supports both smart execution modes:
    - Smart MCP: LLM analyzes user prompt and discovers/selects appropriate tools
    - Direct execution: Traditional tool name + arguments (fallback mode)
    
    Features:
    - HTTP and stdio MCP servers with automatic connection management
    - Template variable resolution and comprehensive error handling
    - LangGraph agents for intelligent tool orchestration
    """
    
    NODE_TYPE = "mcp_tool"
    
    def __init__(self, client_manager: Optional[MCPClientManager] = None):
        super().__init__(default_timeout=300)  # 5 minute default for MCP tools
        self.client_manager = client_manager or MCPClientManager()
        self._langchain_mcp_clients = {}  # Cache for LangChain MCP clients
        self._smart_agents = {}  # Cache for smart agents
    
    async def execute_impl(self, node: WorkflowNode, context: ExecutionContext) -> ExecutionResult:
        """Execute MCP tool node with smart LLM-based or direct execution."""
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Parse and validate configuration
            config = MCPToolNodeConfig.model_validate(node.config)
            
            logger.info(
                "Starting MCP tool execution",
                node_id=node.id,
                smart_mcp_enabled=config.smart_mcp_enabled,
                server_type=config.server.type,
                server_url=config.server.url or config.server.command
            )
            
            # Route execution based on smart_mcp_enabled flag
            if config.smart_mcp_enabled and LANGCHAIN_MCP_AVAILABLE:
                return await self._execute_smart_mode(node, context, config, start_time)
            else:
                return await self._execute_direct_mode(node, context, config, start_time)
                
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
    
    async def _execute_smart_mode(
        self, 
        node: WorkflowNode, 
        context: ExecutionContext, 
        config: MCPToolNodeConfig, 
        start_time: datetime
    ) -> ExecutionResult:
        """Execute using smart LLM-based tool discovery and selection."""
        
        logger.info(
            "Executing smart MCP mode",
            node_id=node.id,
            llm_provider=config.llm_config.provider,
            llm_model=config.llm_config.model
        )
        
        try:
            # Resolve template variables in context data directly (like Agent executor)
            resolved_context = {}
            if config.context_data:
                for key, value in config.context_data.items():
                    if isinstance(value, str):
                        # Direct template resolution like Agent executor
                        resolved_value = await context.resolve_template(value)
                        resolved_context[key] = resolved_value
                    else:
                        resolved_context[key] = value
            
            # Create LangChain MCP client
            mcp_client = await self._get_langchain_mcp_client(config)
            
            # Get available tools from MCP server
            tools = await mcp_client.get_tools()
            
            if not tools:
                raise MCPError("No tools available from MCP server")
            
            # Handle both tool objects and dictionaries
            def get_tool_name(tool):
                if hasattr(tool, 'name'):
                    return tool.name
                elif isinstance(tool, dict) and 'name' in tool:
                    return tool['name']
                else:
                    return str(tool)
            
            logger.info(
                "Discovered MCP tools",
                node_id=node.id,
                tool_count=len(tools),
                tool_names=[get_tool_name(tool) for tool in tools[:5]]  # Log first 5 tool names
            )
            
            # Create LLM client for smart agent
            llm_client = await LLMClientFactory.create_langchain_client(config.llm_config)
            
            # Build smart agent with tool binding
            agent = await self._build_smart_agent(llm_client, tools, config)
            
            # Resolve user prompt template directly (like Agent executor)
            resolved_user_prompt = await context.resolve_template(config.user_prompt)
            
            # Prepare user message with resolved context
            user_message = await self._prepare_smart_prompt_with_resolved_prompt(resolved_user_prompt, resolved_context, tools, config)
            
            logger.info(
                "Invoking smart agent",
                node_id=node.id,
                user_prompt_length=len(config.user_prompt),
                context_keys=list(resolved_context.keys())
            )
            
            # Execute via smart agent with recursion limit
            logger.info(f"🚀 Invoking agent with recursion limit: {config.max_tool_calls * 2}")
            
            # CRITICAL FIX: Ensure proper async tool execution for LangChain MCP
            try:
                agent_response = await agent.ainvoke(
                    {"messages": [HumanMessage(content=user_message)]},
                    config={
                        "recursion_limit": config.max_tool_calls * 2,  # Set reasonable limit
                        "configurable": {
                            "thread_id": f"mcp-{node.id}-{context.run_id}"  # Unique thread for MCP execution
                        }
                    }
                )
            except Exception as invoke_error:
                # Check for auth/token expiry errors first — retry once with fresh token
                err_str = str(invoke_error)
                err_lower = err_str.lower()
                is_auth_error = (
                    isinstance(invoke_error, OpenAIAuthError)
                    or "401" in err_str
                    or ("token" in err_lower and "expired" in err_lower)
                    or "unauthorized" in err_lower
                )

                if is_auth_error:
                    logger.warning(
                        "Authentication error in MCP agent, refreshing token and retrying once",
                        node_id=node.id,
                        error=err_str
                    )
                    # Invalidate cached token + client, rebuild agent with fresh credentials
                    LLMClientFactory.invalidate_cache(config.llm_config)
                    llm_client = await LLMClientFactory.create_langchain_client(config.llm_config)
                    agent = await self._build_smart_agent(llm_client, tools, config)
                    agent_response = await agent.ainvoke(
                        {"messages": [HumanMessage(content=user_message)]},
                        config={
                            "recursion_limit": config.max_tool_calls * 2,
                            "configurable": {
                                "thread_id": f"mcp-{node.id}-{context.run_id}-retry"
                            }
                        }
                    )
                # Handle specific LangChain MCP async issues
                elif "StructuredTool" in err_str or "sync" in err_lower:
                    logger.warning("Detected sync/async tool issue, retrying with different configuration")
                    # Retry without complex configuration
                    agent_response = await agent.ainvoke(
                        {"messages": [HumanMessage(content=user_message)]}
                    )
                else:
                    raise
            
            # Process agent response
            processed_result, context_updates = await self._process_smart_response(
                agent_response, node, config, resolved_context, len(tools)
            )
            
            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            metrics.network_calls = 1  # Could be multiple tool calls, but count as 1 logical operation
            
            logger.info(
                "Smart MCP execution completed successfully",
                node_id=node.id,
                duration_ms=metrics.duration_ms
            )
            
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                data=processed_result,
                metrics=metrics,
                context_updates=context_updates
            )
            
        except Exception as e:
            logger.error(
                "Smart MCP execution failed",
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
            result.set_error(e, f"Smart MCP execution failed for node {node.id}")
            return result
    
    async def _execute_direct_mode(
        self, 
        node: WorkflowNode, 
        context: ExecutionContext, 
        config: MCPToolNodeConfig, 
        start_time: datetime
    ) -> ExecutionResult:
        """Execute using direct tool invocation (fallback/legacy mode)."""
        
        logger.info(
            "Executing direct MCP mode (fallback)",
            node_id=node.id,
            reason="smart_mcp_disabled" if not config.smart_mcp_enabled else "langchain_unavailable"
        )
        
        try:
            # For direct mode, get tool_name from config
            tool_name = config.tool_name
            
            if not tool_name:
                raise ValueError("Direct MCP mode requires tool_name in configuration.")
            
            # Use tool_arguments from config for direct mode
            resolved_args = config.tool_arguments or {}
            
            # Resolve template variables in arguments directly (like Agent executor)
            if resolved_args:
                final_resolved_args = {}
                for key, value in resolved_args.items():
                    if isinstance(value, str):
                        # Debug template resolution
                        logger.info(f"🔍 DEBUG: Resolving template '{value}' for key '{key}'")
                        
                        # Check what's in the context
                        workflow_input = await context.get("workflow.input")
                        logger.info(f"🔍 DEBUG: workflow.input in context: {workflow_input}")
                        
                        resolved_value = await context.resolve_template(value)
                        logger.info(f"🔍 DEBUG: Template '{value}' resolved to '{resolved_value}'")
                        final_resolved_args[key] = resolved_value
                    else:
                        final_resolved_args[key] = value
                resolved_args = final_resolved_args
            
            logger.info(
                "Executing direct MCP tool call",
                node_id=node.id,
                tool_name=tool_name,
                resolved_args=resolved_args
            )
            
            # Execute tool via MCP client manager
            result = await self.client_manager.call_tool(
                config.server,
                tool_name,
                resolved_args
            )
            
            # Process response using existing logic
            processed_result, context_updates = await self._process_response(
                result, node, config, tool_name, resolved_args
            )
            
            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            metrics.network_calls = 1
            
            logger.info(
                "Direct MCP execution completed successfully",
                node_id=node.id,
                tool_name=tool_name,
                duration_ms=metrics.duration_ms
            )
            
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                data=processed_result,
                metrics=metrics,
                context_updates=context_updates
            )
            
        except MCPError as e:
            logger.error(
                "Direct MCP tool execution failed",
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
            result.set_error(e, f"Direct MCP tool execution failed for node {node.id}")
            return result
    
    async def _get_langchain_mcp_client(self, config: MCPToolNodeConfig) -> Any:
        """Get or create cached LangChain MCP client."""
        
        # Create cache key based on server configuration
        server_key = f"{config.server.type}:{config.server.url or config.server.command}"
        
        if server_key in self._langchain_mcp_clients:
            return self._langchain_mcp_clients[server_key]
        
        logger.info(
            "Creating LangChain MCP client",
            server_type=config.server.type,
            server_url=config.server.url or config.server.command
        )
        
        # Configure MCP client based on server type
        if config.server.type in ["http", "streamable-http"]:
            client_config = {
                "mcp_server": {
                    "transport": "streamable_http" if config.server.type == "streamable-http" else "http",
                    "url": config.server.url
                }
            }
            
            if config.server.headers:
                client_config["mcp_server"]["headers"] = config.server.headers
                
        elif config.server.type == "sse":
            client_config = {
                "mcp_server": {
                    "transport": "sse",
                    "url": config.server.url
                }
            }
        else:
            raise ValueError(f"Unsupported MCP server type for LangChain: {config.server.type}")
        
        # Create MultiServerMCPClient
        mcp_client = MultiServerMCPClient(client_config)
        
        # Cache the client
        self._langchain_mcp_clients[server_key] = mcp_client
        
        logger.info(f"Created and cached LangChain MCP client: {server_key}")
        return mcp_client
    
    async def _build_smart_agent(self, llm_client: Any, tools: List[Any], config: MCPToolNodeConfig) -> Any:
        """Build LangGraph smart agent with MCP tools."""
        
        logger.info(
            "Building smart agent",
            tool_count=len(tools),
            max_tool_calls=config.max_tool_calls
        )
        
        # Filter tools based on preferred_tools if specified
        if config.preferred_tools:
            preferred_tool_names = set(config.preferred_tools)
            
            def get_tool_name(tool):
                if hasattr(tool, 'name'):
                    return tool.name
                elif isinstance(tool, dict) and 'name' in tool:
                    return tool['name']
                else:
                    return str(tool)
            
            filtered_tools = [tool for tool in tools if get_tool_name(tool) in preferred_tool_names]
            
            if filtered_tools:
                tools = filtered_tools
                logger.info(
                    "Filtered tools by preferences",
                    preferred_tools=config.preferred_tools,
                    filtered_count=len(tools)
                )
        
        # Limit tools to prevent overwhelming the agent
        if len(tools) > config.max_tool_calls:
            tools = tools[:config.max_tool_calls]
            logger.info(f"Limited tools to {config.max_tool_calls} for agent efficiency")
        
        # Create LangGraph agent
        def call_model(state: MessagesState):
            """Call the LLM with tool binding."""
            logger.info(f"🤖 LangGraph call_model - Messages count: {len(state['messages'])}")
            response = llm_client.bind_tools(tools).invoke(state["messages"])
            
            # Debug tool calls
            if hasattr(response, 'tool_calls') and response.tool_calls:
                logger.info(f"🛠️ Tool calls requested: {[tc.get('name', 'unknown') for tc in response.tool_calls]}")
            else:
                logger.info("✅ No more tool calls - agent should finish")
            
            return {"messages": response}
        
        # Create debug wrapper for async tool execution
        async def debug_tool_node(state: MessagesState):
            """Debug wrapper for async tool node execution."""
            logger.info(f"🛠️ ToolNode executing - Messages count: {len(state['messages'])}")
            
            # Get tool calls from the last message
            last_message = state["messages"][-1] if state["messages"] else None
            if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                for tc in last_message.tool_calls:
                    tool_name = tc.get('name', 'unknown') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown')
                    tool_args = tc.get('args', {}) if isinstance(tc, dict) else getattr(tc, 'args', {})
                    logger.info(f"   → Executing tool: {tool_name} with args: {tool_args}")
            
            # Execute tools asynchronously
            tool_node = ToolNode(tools)
            result = await tool_node.ainvoke(state)
            
            # Debug tool responses
            if result and 'messages' in result:
                for msg in result['messages']:
                    if hasattr(msg, 'content'):
                        content_preview = str(msg.content)[:200] + "..." if len(str(msg.content)) > 200 else str(msg.content)
                        logger.info(f"   ← Tool response preview: {content_preview}")
            
            logger.info(f"🔧 ToolNode completed - Result messages: {len(result.get('messages', []))}")
            return result
        
        # Build the graph
        builder = StateGraph(MessagesState)
        builder.add_node("call_model", call_model)
        builder.add_node("tools", debug_tool_node)
        builder.add_edge(START, "call_model")
        builder.add_conditional_edges(
            "call_model",
            tools_condition,
        )
        builder.add_edge("tools", "call_model")
        
        # FIX: Set recursion limit to prevent infinite loops
        agent = builder.compile(checkpointer=None, debug=False)
        
        logger.info("Successfully built smart agent with tool binding and recursion limit")
        return agent
    
    async def _prepare_smart_prompt_with_resolved_prompt(
        self, 
        resolved_user_prompt: str,
        resolved_context: Dict[str, Any], 
        tools: List[Any],
        config: MCPToolNodeConfig
    ) -> str:
        """Prepare enhanced prompt for smart agent execution with pre-resolved user prompt."""
        
        # Start with pre-resolved user prompt
        prompt_parts = [resolved_user_prompt]
        
        # Add context information if available
        if resolved_context:
            context_str = "\n".join([
                f"- {key}: {value}" 
                for key, value in resolved_context.items()
            ])
            prompt_parts.append(f"\nContext Information:\n{context_str}")
        
        # Add tool guidance if preferred tools are specified
        if config.preferred_tools:
            preferred_str = ", ".join(config.preferred_tools)
            prompt_parts.append(f"\nPreferred Tools: {preferred_str}")
        
        # Add output format guidance
        if config.output_format == "json":
            prompt_parts.append(
                "\nIMPORTANT: Provide your final response in valid JSON format. "
                "Structure the response clearly with relevant fields based on the task."
            )
        elif config.output_format == "text":
            prompt_parts.append(
                "\nProvide your response in clear, natural language text format."
            )
        
        # Add tool usage instructions  
        def get_tool_name(tool):
            if hasattr(tool, 'name'):
                return tool.name
            elif isinstance(tool, dict) and 'name' in tool:
                return tool['name']
            else:
                return str(tool)
        
        tool_names = [get_tool_name(tool) for tool in tools[:10]]  # Show first 10 tools
        tool_list = ", ".join(tool_names)
        if len(tools) > 10:
            tool_list += f", and {len(tools) - 10} more tools"
        
        prompt_parts.append(
            f"\nAvailable tools: {tool_list}\n"
            "Use the most appropriate tools to accomplish the task. "
            "Once you have gathered the necessary information, provide your final response. "
            "IMPORTANT: Do not call tools repeatedly - gather the information you need and then give your final answer."
        )
        
        final_prompt = "\n".join(prompt_parts)
        
        logger.debug(
            "Prepared smart prompt",
            prompt_length=len(final_prompt),
            context_fields=len(resolved_context),
            has_preferred_tools=bool(config.preferred_tools)
        )
        
        return final_prompt
    
    async def _process_smart_response(
        self, 
        agent_response: Any, 
        node: WorkflowNode, 
        config: MCPToolNodeConfig, 
        resolved_context: Dict[str, Any], 
        tool_count: int
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Process smart agent response and extract structured data."""
        
        logger.info(
            "Processing smart agent response",
            node_id=node.id,
            response_type=type(agent_response).__name__
        )
        
        # Extract final message from agent response
        final_message = None
        tool_calls_made = []
        
        if isinstance(agent_response, dict) and "messages" in agent_response:
            messages = agent_response["messages"]
            if messages:
                final_message = messages[-1]
                
                # Count tool calls in the conversation
                for message in messages:
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        # Handle both tool call objects and dictionaries
                        for tc in message.tool_calls:
                            if hasattr(tc, 'name'):
                                tool_calls_made.append(tc.name)
                            elif isinstance(tc, dict) and 'name' in tc:
                                tool_calls_made.append(tc['name'])
                            else:
                                tool_calls_made.append(str(tc))
        
        # Extract content from final message
        response_content = ""
        if final_message:
            if hasattr(final_message, 'content'):
                response_content = final_message.content
            else:
                response_content = str(final_message)
        
        # Try to parse JSON if expected
        parsed_content = None
        if config.output_format == "json":
            try:
                # Handle markdown JSON blocks
                json_content = response_content
                if "```json" in json_content:
                    start_idx = json_content.find("```json") + 7
                    end_idx = json_content.find("```", start_idx)
                    if end_idx != -1:
                        json_content = json_content[start_idx:end_idx].strip()
                
                parsed_content = json.loads(json_content)
                logger.info(
                    "Successfully parsed JSON response",
                    node_id=node.id,
                    json_fields=list(parsed_content.keys()) if isinstance(parsed_content, dict) else "not_dict"
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(
                    "Failed to parse JSON response, using text format",
                    node_id=node.id,
                    error=str(e)
                )
                parsed_content = {"response": response_content}
        
        # Prepare result data
        result_data = {
            "response": response_content,
            "parsed": parsed_content,
            "smart_execution": True,
            "tool_calls_made": tool_calls_made,
            "tools_available": tool_count,
            "llm_provider": config.llm_config.provider,
            "llm_model": config.llm_config.model,
            "user_prompt": config.user_prompt,
            "resolved_context": resolved_context,
            "output_format": config.output_format,
            "node_name": node.name or node.config.get('name', node.id)
        }
        
        # Create context updates
        main_output = parsed_content if parsed_content is not None else response_content
        context_updates = {
            f"nodes.{node.id}.output": main_output,
            f"nodes.{node.id}.output.full": result_data,
            f"nodes.{node.id}.response": response_content,
            f"nodes.{node.id}.tool_calls_made": tool_calls_made,
            f"nodes.{node.id}.success": True
        }
        
        # Map individual JSON properties if available
        if isinstance(parsed_content, dict):
            for property_name, property_value in parsed_content.items():
                context_updates[f"nodes.{node.id}.output.{property_name}"] = property_value
            
            logger.info(
                "Mapped smart response properties to workflow variables",
                node_id=node.id,
                properties=list(parsed_content.keys())
            )
        
        logger.info(
            "Smart response processing completed",
            node_id=node.id,
            tool_calls_count=len(tool_calls_made),
            has_parsed_content=parsed_content is not None
        )
        
        return result_data, context_updates

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
        
        # DEBUG: Log the JSON detection process
        logger.info(
            "Starting JSON detection process",
            node_id=node.id,
            tool_name=tool_name,
            output_format=output_format,
            result_type=type(result).__name__,
            has_content_key=hasattr(result, 'get') and 'content' in result if hasattr(result, 'get') else False
        )
        
        # Try to detect if result contains JSON content
        json_content = None
        is_json_output = False
        
        # Parse JSON content for all output formats that expect JSON
        if output_format in ['json', 'json_object', 'auto']:
            # Try to extract JSON content from various result formats
            if isinstance(result, dict):
                # Case 1: Result is already a dictionary
                json_content = result
                is_json_output = True
            elif isinstance(result, str):
                # Case 2: Result is a JSON string
                try:
                    json_content = json.loads(result.strip())
                    is_json_output = True
                except (json.JSONDecodeError, AttributeError):
                    is_json_output = False
            elif hasattr(result, 'get') and result.get('content'):
                # Case 3: Handle MCP tool response format
                content = result.get('content')
                
                # Case 3a: content is a direct string
                if isinstance(content, str):
                    try:
                        json_content = json.loads(content.strip())
                        is_json_output = True
                    except (json.JSONDecodeError, AttributeError):
                        is_json_output = False
                
                # Case 3b: content is an array with text objects (MCP standard format)
                elif isinstance(content, list) and len(content) > 0:
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'text' and 'text' in item:
                            try:
                                json_content = json.loads(item['text'].strip())
                                is_json_output = True
                                break  # Use first valid JSON found
                            except (json.JSONDecodeError, AttributeError):
                                continue
                        # Also handle direct text content
                        elif isinstance(item, dict) and 'text' in item:
                            try:
                                json_content = json.loads(item['text'].strip())
                                is_json_output = True
                                break
                            except (json.JSONDecodeError, AttributeError):
                                continue
            
            # For explicit json/json_object formats, default to structured if no parsing succeeded
            if output_format in ['json', 'json_object'] and not is_json_output:
                is_json_output = True  # Force JSON processing for explicit formats
        
        # DEBUG: Log the result of JSON detection
        logger.info(
            "JSON detection completed",
            node_id=node.id,
            tool_name=tool_name,
            is_json_output=is_json_output,
            json_content_type=type(json_content).__name__ if json_content is not None else "None",
            json_content_keys=list(json_content.keys()) if isinstance(json_content, dict) else "not_dict"
        )
        
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
                "output_format": "json",
                "node_name": node.name or node.config.get('name', node.id)  # Include node display name
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
                "output_format": "text",
                "node_name": node.name or node.config.get('name', node.id)  # Include node display name
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
    
    
    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate smart MCP tool node configuration."""
        result = ValidationResult(is_valid=True)
        
        try:
            # Log the config for debugging
            logger.debug(f"Validating MCP config: {config}")
            
            # Validate using Pydantic schema (will validate LLMConfig too)
            MCPToolNodeConfig.model_validate(config)
            
            logger.debug("MCP config validation successful")
            
        except Exception as e:
            logger.error(f"MCP config validation failed: {str(e)} - Config: {config}")
            result.add_error(
                f"Invalid smart MCP tool configuration: {str(e)}",
                field="config",
                suggestion="Check server configuration, LLM settings, and user_prompt"
            )
            return result
        
        # Additional validation for server configuration
        server_config = config.get("server", {})
        server_type = server_config.get("type", "http")
        
        if server_type in ["http", "streamable-http"]:
            url = server_config.get("url")
            if not url:
                result.add_error(
                    f"{server_type.upper()} MCP server requires 'url' field",
                    field="server.url",
                    suggestion="Provide the HTTP URL of the MCP server"
                )
            elif not url.startswith(("http://", "https://")):
                result.add_error(
                    "MCP server URL must be a valid HTTP/HTTPS URL",
                    field="server.url"
                )
        
        elif server_type == "sse":
            url = server_config.get("url")
            if not url:
                result.add_error(
                    "SSE MCP server requires 'url' field",
                    field="server.url",
                    suggestion="Provide the SSE URL of the MCP server"
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
                    "Stdio MCP servers are not yet fully implemented for smart execution",
                    field="server.type"
                )
        
        # Smart MCP specific validations
        smart_mcp_enabled = config.get("smart_mcp_enabled", True)
        
        if smart_mcp_enabled:
            # Check if LangChain dependencies are available
            if not LANGCHAIN_MCP_AVAILABLE:
                result.add_error(
                    "Smart MCP requires LangChain dependencies. "
                    "Install with: pip install langchain-mcp-adapters langchain-openai langchain-core langgraph",
                    field="smart_mcp_enabled",
                    suggestion="Install LangChain MCP dependencies or set smart_mcp_enabled=false"
                )
            
            # Validate user_prompt is provided
            user_prompt = config.get("user_prompt")
            if not user_prompt or not user_prompt.strip():
                result.add_error(
                    "Smart MCP requires 'user_prompt' field",
                    field="user_prompt",
                    suggestion="Provide a natural language description of the task"
                )
            
            # Validate LLM configuration
            llm_config = config.get("llm_config", {})
            if not llm_config:
                result.add_error(
                    "Smart MCP requires 'llm_config' field",
                    field="llm_config",
                    suggestion="Provide LLM configuration for smart execution"
                )
            else:
                # LLMConfig validation is handled by Pydantic - endpoint and deployment auto-populate from env
                pass
        
        else:
            # Direct mode validation - requires tool_name
            tool_name = config.get("tool_name")
            if not tool_name:
                result.add_error(
                    "Direct MCP mode requires 'tool_name'",
                    field="tool_name",
                    suggestion="Provide tool_name for direct execution or enable smart_mcp_enabled=true"
                )
        
        # Validate max_tool_calls
        max_tool_calls = config.get("max_tool_calls", 5)
        if max_tool_calls < 1 or max_tool_calls > 20:
            result.add_warning(
                "max_tool_calls should be between 1 and 20 for optimal performance",
                field="max_tool_calls",
                suggestion="Use 3-8 tool calls for most tasks"
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
        """Clean up MCP client connections and smart execution caches."""
        # Clean up direct MCP client connections
        if self.client_manager:
            await self.client_manager.disconnect_all()
        
        # Clean up LangChain MCP client caches
        self._langchain_mcp_clients.clear()
        self._smart_agents.clear()
        
        # Clean up LLM client factory caches
        from ..llm.client_factory import LLMClientFactory
        LLMClientFactory.invalidate_cache()
        
        logger.info("Cleaned up MCP executor caches and connections")


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
                "os_type": "${workflow.input.os_type}",
                "version": "${workflow.input.version}"
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