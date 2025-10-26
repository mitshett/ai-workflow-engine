"""MCP Client Manager

Manages MCP client connections with pooling, caching, and lifecycle management.
Provides a centralized interface for workflow nodes to interact with MCP servers.
"""

import asyncio
import hashlib
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from ..core.schemas import MCPServerConfig
from .http_client import MCPClient, create_mcp_client, MCPError

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Centralized manager for MCP client connections."""
    
    def __init__(self):
        """Initialize MCP client manager."""
        self.clients: Dict[str, MCPClient] = {}
        self.client_metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
    
    def _get_server_signature(self, server_config: MCPServerConfig) -> str:
        """Create unique signature for server configuration.
        
        This allows connection reuse for identical server configs.
        """
        if server_config.type == "http":
            # For HTTP servers, use URL as signature
            url = server_config.url
            # Check if URL already has protocol prefix
            if not (url.startswith('http://') or url.startswith('https://')):
                url = f"http://{url}"
            return url
        
        elif server_config.type == "stdio":
            # For stdio servers, hash command + args
            command_str = server_config.command
            if server_config.args:
                command_str += ":" + ":".join(server_config.args)
            
            # Create deterministic hash
            signature = hashlib.md5(command_str.encode()).hexdigest()[:16]
            return f"stdio://{signature}"
        
        else:
            raise ValueError(f"Unsupported server type: {server_config.type}")
    
    async def get_client(self, server_config: MCPServerConfig) -> MCPClient:
        """Get or create MCP client for server configuration.
        
        Args:
            server_config: MCP server configuration
            
        Returns:
            Connected MCP client
            
        Raises:
            MCPError: If connection fails
        """
        signature = self._get_server_signature(server_config)
        
        async with self._lock:
            # Check if client already exists and is connected
            if signature in self.clients:
                client = self.clients[signature]
                
                # Test if connection is still alive
                if await self._test_client_connection(client):
                    logger.debug(f"Reusing existing MCP client for {signature}")
                    return client
                else:
                    logger.info(f"Removing stale MCP client for {signature}")
                    await self._cleanup_client(signature)
            
            # Create new client
            logger.info(f"Creating new MCP client for {signature}")
            client = create_mcp_client(server_config)
            
            try:
                await client.connect()
                
                # Store client and metadata
                self.clients[signature] = client
                self.client_metadata[signature] = {
                    'server_config': server_config,
                    'created_at': datetime.now(timezone.utc),
                    'last_used': datetime.now(timezone.utc),
                    'connection_count': 0
                }
                
                logger.info(f"Successfully created MCP client for {signature}")
                return client
                
            except Exception as e:
                logger.error(f"Failed to create MCP client for {signature}: {e}")
                raise MCPError(f"Failed to connect to MCP server: {str(e)}")
    
    async def call_tool(
        self, 
        server_config: MCPServerConfig, 
        tool_name: str, 
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call a tool on an MCP server.
        
        Args:
            server_config: MCP server configuration
            tool_name: Name of tool to call
            arguments: Tool arguments
            
        Returns:
            Tool execution result
            
        Raises:
            MCPError: If tool call fails
        """
        client = await self.get_client(server_config)
        signature = self._get_server_signature(server_config)
        
        try:
            # Update usage metadata
            if signature in self.client_metadata:
                metadata = self.client_metadata[signature]
                metadata['last_used'] = datetime.now(timezone.utc)
                metadata['connection_count'] += 1
            
            # Execute tool call
            result = await client.call_tool(tool_name, arguments)
            
            logger.debug(f"Successfully called tool {tool_name} on {signature}")
            return result
            
        except Exception as e:
            logger.error(f"Tool call failed for {tool_name} on {signature}: {e}")
            raise
    
    async def list_server_tools(self, server_config: MCPServerConfig) -> List[Dict[str, Any]]:
        """List available tools from an MCP server.
        
        Args:
            server_config: MCP server configuration
            
        Returns:
            List of available tools with schemas
            
        Raises:
            MCPError: If tool discovery fails
        """
        client = await self.get_client(server_config)
        signature = self._get_server_signature(server_config)
        
        try:
            tools = await client.list_tools()
            logger.debug(f"Discovered {len(tools)} tools from {signature}")
            return tools
            
        except Exception as e:
            logger.error(f"Failed to list tools from {signature}: {e}")
            raise MCPError(f"Failed to discover tools: {str(e)}")
    
    async def _test_client_connection(self, client: MCPClient) -> bool:
        """Test if MCP client connection is still alive."""
        try:
            # Try a simple operation to test connection
            await client.list_tools()
            return True
        except Exception as e:
            logger.debug(f"Client connection test failed: {e}")
            return False
    
    async def _cleanup_client(self, signature: str) -> None:
        """Clean up a client connection."""
        if signature in self.clients:
            try:
                client = self.clients[signature]
                await client.disconnect()
            except Exception as e:
                logger.debug(f"Error during client cleanup for {signature}: {e}")
            finally:
                del self.clients[signature]
                if signature in self.client_metadata:
                    del self.client_metadata[signature]
    
    async def disconnect_all(self) -> None:
        """Disconnect all MCP clients."""
        logger.info("Disconnecting all MCP clients")
        
        signatures = list(self.clients.keys())
        for signature in signatures:
            await self._cleanup_client(signature)
    
    def get_client_stats(self) -> Dict[str, Any]:
        """Get statistics about managed MCP clients."""
        return {
            'total_clients': len(self.clients),
            'clients': {
                signature: {
                    'server_type': metadata['server_config'].type,
                    'created_at': metadata['created_at'].isoformat(),
                    'last_used': metadata['last_used'].isoformat(),
                    'connection_count': metadata['connection_count']
                }
                for signature, metadata in self.client_metadata.items()
            }
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect_all()