"""Generic MCP Client Manager

Manages MCP client connections with pooling, caching, and lifecycle management.
Provides a centralized interface for workflow nodes to interact with MCP servers
using any transport protocol (stdio, http, sse, streamable-http).
"""

import asyncio
import hashlib
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from ..core.schemas import MCPServerConfig
from .transport import MCPTransport, MCPTransportError, create_transport

logger = logging.getLogger(__name__)


class MCPError(Exception):
    """MCP-related errors (for backward compatibility)."""
    def __init__(self, message: str, code: int = -32603):
        self.message = message
        self.code = code
        super().__init__(message)


class MCPClientManager:
    """Centralized manager for MCP transport connections."""
    
    def __init__(self):
        """Initialize MCP client manager."""
        self.transports: Dict[str, MCPTransport] = {}
        self.transport_metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
    
    def _get_server_signature(self, server_config: MCPServerConfig) -> str:
        """Create unique signature for server configuration.
        
        This allows connection reuse for identical server configs.
        """
        if server_config.type in ["http", "sse", "streamable-http"]:
            # For HTTP-based servers, use URL as signature with transport type
            url = server_config.url
            if not (url.startswith('http://') or url.startswith('https://')):
                url = f"http://{url}"
            return f"{server_config.type}:{url}"
        
        elif server_config.type == "stdio":
            # For stdio servers, hash command + args
            command_str = server_config.command
            if server_config.args:
                command_str += ":" + ":".join(server_config.args)
            
            # Create deterministic hash
            signature = hashlib.md5(command_str.encode()).hexdigest()[:16]
            return f"stdio://{signature}"
        
        else:
            raise MCPError(f"Unsupported server type: {server_config.type}")
    
    async def get_transport(self, server_config: MCPServerConfig) -> MCPTransport:
        """Get or create MCP transport for server configuration.
        
        Args:
            server_config: MCP server configuration
            
        Returns:
            Connected MCP transport
            
        Raises:
            MCPError: If connection fails
        """
        signature = self._get_server_signature(server_config)
        
        async with self._lock:
            # Check if transport already exists and is connected
            if signature in self.transports:
                transport = self.transports[signature]
                
                # Test if connection is still alive
                if transport.is_connected:
                    logger.debug(f"Reusing existing MCP transport for {signature}")
                    return transport
                else:
                    logger.info(f"Removing stale MCP transport for {signature}")
                    await self._cleanup_transport(signature)
            
            # Create new transport
            logger.info(f"Creating new MCP transport for {signature}")
            transport = create_transport(server_config)
            
            try:
                await transport.initialize()
                
                # Store transport and metadata
                self.transports[signature] = transport
                self.transport_metadata[signature] = {
                    'server_config': server_config,
                    'created_at': datetime.now(timezone.utc),
                    'last_used': datetime.now(timezone.utc),
                    'connection_count': 0,
                    'capabilities': transport.capabilities,
                    'server_info': transport.server_info
                }
                
                logger.info(f"Successfully created MCP transport for {signature}")
                return transport
                
            except MCPTransportError as e:
                logger.error(f"Failed to create MCP transport for {signature}: {e}")
                raise MCPError(f"Failed to connect to MCP server: {str(e)}")
            except Exception as e:
                logger.error(f"Failed to create MCP transport for {signature}: {e}")
                raise MCPError(f"Failed to connect to MCP server: {str(e)}")
    
    # Backward compatibility method
    async def get_client(self, server_config: MCPServerConfig) -> MCPTransport:
        """Get or create MCP transport (backward compatibility).
        
        Returns MCP transport that has the same interface as the old MCPClient.
        """
        return await self.get_transport(server_config)
    
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
        transport = await self.get_transport(server_config)
        signature = self._get_server_signature(server_config)
        
        try:
            # Update usage metadata
            if signature in self.transport_metadata:
                metadata = self.transport_metadata[signature]
                metadata['last_used'] = datetime.now(timezone.utc)
                metadata['connection_count'] += 1
            
            # Execute tool call
            result = await transport.call_tool(tool_name, arguments)
            
            logger.debug(f"Successfully called tool {tool_name} on {signature}")
            return result
            
        except MCPTransportError as e:
            logger.error(f"Tool call failed for {tool_name} on {signature}: {e}")
            raise MCPError(str(e))
        except Exception as e:
            logger.error(f"Tool call failed for {tool_name} on {signature}: {e}")
            raise MCPError(str(e))
    
    async def list_server_tools(self, server_config: MCPServerConfig) -> List[Dict[str, Any]]:
        """List available tools from an MCP server.
        
        Args:
            server_config: MCP server configuration
            
        Returns:
            List of available tools with schemas
            
        Raises:
            MCPError: If tool discovery fails
        """
        transport = await self.get_transport(server_config)
        signature = self._get_server_signature(server_config)
        
        try:
            tools = await transport.list_tools()
            logger.debug(f"Discovered {len(tools)} tools from {signature}")
            return tools
            
        except MCPTransportError as e:
            logger.error(f"Failed to list tools from {signature}: {e}")
            raise MCPError(f"Failed to discover tools: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to list tools from {signature}: {e}")
            raise MCPError(f"Failed to discover tools: {str(e)}")
    
    async def _cleanup_transport(self, signature: str) -> None:
        """Clean up a transport connection."""
        if signature in self.transports:
            try:
                transport = self.transports[signature]
                await transport.disconnect()
            except Exception as e:
                logger.debug(f"Error during transport cleanup for {signature}: {e}")
            finally:
                del self.transports[signature]
                if signature in self.transport_metadata:
                    del self.transport_metadata[signature]
    
    async def disconnect_all(self) -> None:
        """Disconnect all MCP transports."""
        logger.info("Disconnecting all MCP transports")
        
        signatures = list(self.transports.keys())
        for signature in signatures:
            await self._cleanup_transport(signature)
    
    def get_client_stats(self) -> Dict[str, Any]:
        """Get statistics about managed MCP transports."""
        return {
            'total_transports': len(self.transports),
            'transports': {
                signature: {
                    'server_type': metadata['server_config'].type,
                    'server_url': getattr(metadata['server_config'], 'url', None) or getattr(metadata['server_config'], 'command', None),
                    'created_at': metadata['created_at'].isoformat(),
                    'last_used': metadata['last_used'].isoformat(),
                    'connection_count': metadata['connection_count'],
                    'capabilities': metadata.get('capabilities', {}),
                    'server_info': metadata.get('server_info', {})
                }
                for signature, metadata in self.transport_metadata.items()
            }
        }
    
    # Backward compatibility method
    def get_client_stats_legacy(self) -> Dict[str, Any]:
        """Get statistics in legacy format (backward compatibility)."""
        stats = self.get_client_stats()
        return {
            'total_clients': stats['total_transports'],
            'clients': stats['transports']
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect_all()