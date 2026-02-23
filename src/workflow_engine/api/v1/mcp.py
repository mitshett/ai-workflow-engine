"""
MCP Tool Discovery API (v1)

Provides endpoints for discovering tools from MCP servers.
Used by the frontend to populate tool dropdowns and auto-fill arguments.

Author: AI Workflow Engine Team
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
import logging

from ...core.schemas import MCPServerConfig
from ...mcp.client_manager import MCPClientManager, MCPError

logger = logging.getLogger(__name__)

# Shared MCP client manager instance
_mcp_client_manager: Optional[MCPClientManager] = None


def get_mcp_client_manager() -> MCPClientManager:
    """Get or create the shared MCP client manager."""
    global _mcp_client_manager
    if _mcp_client_manager is None:
        _mcp_client_manager = MCPClientManager()
    return _mcp_client_manager


# Create router
router = APIRouter(
    prefix="/api/v1/mcp",
    tags=["mcp-discovery"],
    responses={
        400: {"description": "Invalid server configuration"},
        500: {"description": "Internal server error"},
    },
)


# Request/Response models

class MCPDiscoverRequest(BaseModel):
    """Request to discover tools from an MCP server."""
    server_url: str = Field(..., description="MCP server URL")
    server_type: str = Field("streamable-http", description="Transport type: http, streamable-http, sse, stdio")
    headers: Optional[Dict[str, str]] = Field(None, description="Optional HTTP headers")
    timeout: int = Field(30, ge=1, le=120, description="Connection timeout in seconds")

    @field_validator('server_url', mode='before')
    @classmethod
    def strip_url(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class MCPToolSchema(BaseModel):
    """Schema for a discovered MCP tool."""
    name: str = Field(..., description="Tool name")
    description: Optional[str] = Field(None, description="Tool description")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for tool arguments")


class MCPDiscoverResponse(BaseModel):
    """Response containing discovered tools from an MCP server."""
    success: bool = Field(..., description="Whether discovery succeeded")
    server_url: str = Field(..., description="The server URL that was queried")
    tools: List[MCPToolSchema] = Field(default_factory=list, description="Discovered tools")
    error: Optional[str] = Field(None, description="Error message if discovery failed")


# Endpoints

@router.post(
    "/discover",
    response_model=MCPDiscoverResponse,
    summary="Discover MCP Tools",
    description="Connect to an MCP server and discover available tools with their schemas",
)
async def discover_tools(request: MCPDiscoverRequest) -> MCPDiscoverResponse:
    """
    Discover available tools from an MCP server.

    Connects to the specified MCP server, calls tools/list,
    and returns the available tools with their input schemas.
    """
    logger.info(f"Discovering tools from MCP server: {request.server_url} (type: {request.server_type})")

    try:
        # Build MCPServerConfig from request
        server_config = MCPServerConfig(
            type=request.server_type,
            url=request.server_url,
            headers=request.headers or {},
            timeout=request.timeout,
        )

        # Get client manager and list tools
        client_manager = get_mcp_client_manager()
        raw_tools = await client_manager.list_server_tools(server_config)

        # Transform to response format
        tools = []
        for tool in raw_tools:
            tools.append(MCPToolSchema(
                name=tool.get("name", ""),
                description=tool.get("description"),
                input_schema=tool.get("inputSchema"),
            ))

        logger.info(f"Discovered {len(tools)} tools from {request.server_url}")

        return MCPDiscoverResponse(
            success=True,
            server_url=request.server_url,
            tools=tools,
        )

    except MCPError as e:
        logger.error(f"MCP error discovering tools from {request.server_url}: {e}")
        return MCPDiscoverResponse(
            success=False,
            server_url=request.server_url,
            tools=[],
            error=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected error discovering tools from {request.server_url}: {e}")
        return MCPDiscoverResponse(
            success=False,
            server_url=request.server_url,
            tools=[],
            error=f"Failed to connect to MCP server: {str(e)}",
        )
