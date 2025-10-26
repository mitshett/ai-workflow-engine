"""AI Workflow Engine - MCP Integration

This module provides Model Context Protocol (MCP) integration:
- MCP server registry and connection management
- MCP transport implementations (stdio, HTTP)
- Connection pooling and health monitoring
- MCP tool execution and result processing
"""

from .client_manager import MCPClientManager
from .http_client import HTTPMCPClient

__all__ = ['MCPClientManager', 'HTTPMCPClient']