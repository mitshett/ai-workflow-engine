"""HTTP MCP Client Implementation

Provides HTTP-based Model Context Protocol client for connecting to MCP servers
over HTTP/HTTPS with JSON-RPC 2.0 protocol support.
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import aiohttp
from ..core.schemas import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPError(Exception):
    """Base exception for MCP-related errors."""
    def __init__(self, message: str, code: int = -32603):
        self.message = message
        self.code = code
        super().__init__(message)


class MCPClient:
    """Abstract base class for MCP clients."""
    
    async def connect(self) -> None:
        """Connect to MCP server."""
        raise NotImplementedError
    
    async def disconnect(self) -> None:
        """Disconnect from MCP server."""
        raise NotImplementedError
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server."""
        raise NotImplementedError
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        raise NotImplementedError


class HTTPMCPClient(MCPClient):
    """HTTP-based MCP client implementation."""
    
    def __init__(self, url: str, timeout: int = 30):
        """Initialize HTTP MCP client.
        
        Args:
            url: MCP server HTTP URL
            timeout: Request timeout in seconds
        """
        self.url = url.rstrip('/')
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        self.request_id = 0
        self._connected = False
        
    async def connect(self) -> None:
        """Connect to HTTP MCP server."""
        if self._connected:
            return
            
        # Create HTTP session with timeout
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={'Content-Type': 'application/json'}
        )
        
        # Test connection with capabilities request
        try:
            await self._make_request('capabilities', {})
            self._connected = True
            logger.info(f"Connected to MCP server at {self.url}")
        except Exception as e:
            if self.session:
                await self.session.close()
                self.session = None
            raise MCPError(f"Failed to connect to MCP server {self.url}: {str(e)}")
    
    async def disconnect(self) -> None:
        """Disconnect from HTTP MCP server."""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        self._connected = False
        logger.info(f"Disconnected from MCP server at {self.url}")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server."""
        if not self._connected:
            await self.connect()
            
        try:
            result = await self._make_request('tools/list', {})
            if result is None:
                result = {}
            return result.get('tools', [])
        except Exception as e:
            logger.error(f"Failed to list tools from {self.url}: {e}")
            raise MCPError(f"Failed to list tools: {str(e)}")
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        if not self._connected:
            await self.connect()
            
        params = {
            'name': tool_name,
            'arguments': arguments
        }
        
        try:
            result = await self._make_request('tools/call', params)
            return result
        except Exception as e:
            logger.error(f"Failed to call tool {tool_name} on {self.url}: {e}")
            raise MCPError(f"Tool call failed: {str(e)}")
    
    async def _make_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make JSON-RPC 2.0 request to MCP server."""
        if not self.session:
            raise MCPError("Not connected to MCP server")
            
        self.request_id += 1
        
        request_data = {
            'jsonrpc': '2.0',
            'id': self.request_id,
            'method': method,
            'params': params
        }
        
        endpoint = f"{self.url}/mcp"
        logger.debug(f"Making MCP request to {endpoint}: {method}")
        
        try:
            async with self.session.post(endpoint, json=request_data) as response:
                if response.status != 200:
                    response_text = await response.text()
                    raise MCPError(f"HTTP {response.status}: {response_text}")
                
                response_data = await response.json()
                
                # Check for JSON-RPC error
                if 'error' in response_data and response_data['error'] is not None:
                    error = response_data['error']
                    error_code = error.get('code', -32603)
                    error_message = error.get('message', 'Unknown error')
                    raise MCPError(f"MCP error: {error_message}", error_code)
                
                # Return result, ensure it's never None
                result = response_data.get('result', {})
                return result if result is not None else {}
                
        except aiohttp.ClientError as e:
            raise MCPError(f"HTTP request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise MCPError(f"Invalid JSON response: {str(e)}")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


class StdioMCPClient(MCPClient):
    """Stdio-based MCP client implementation (placeholder)."""
    
    def __init__(self, command: str, args: Optional[List[str]] = None):
        """Initialize stdio MCP client.
        
        Args:
            command: Command to start MCP server
            args: Command arguments
        """
        self.command = command
        self.args = args or []
        self._connected = False
        
        # For now, raise not implemented
        logger.warning("Stdio MCP client not yet implemented")
    
    async def connect(self) -> None:
        """Connect to stdio MCP server."""
        raise NotImplementedError("Stdio MCP client not yet implemented")
    
    async def disconnect(self) -> None:
        """Disconnect from stdio MCP server."""
        raise NotImplementedError("Stdio MCP client not yet implemented")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server."""
        raise NotImplementedError("Stdio MCP client not yet implemented")
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        raise NotImplementedError("Stdio MCP client not yet implemented")


def create_mcp_client(server_config: MCPServerConfig) -> MCPClient:
    """Factory function to create appropriate MCP client based on server config."""
    if server_config.type == "http":
        if not server_config.url:
            raise ValueError("HTTP MCP server requires URL")
        return HTTPMCPClient(server_config.url, server_config.timeout)
    
    elif server_config.type == "stdio":
        if not server_config.command:
            raise ValueError("Stdio MCP server requires command")
        return StdioMCPClient(server_config.command, server_config.args)
    
    else:
        raise ValueError(f"Unsupported MCP server type: {server_config.type}")