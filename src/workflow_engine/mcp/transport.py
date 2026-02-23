"""Generic MCP Transport Layer

Provides abstract transport implementations for different MCP protocols:
- stdio: Process-based communication  
- http: Standard HTTP JSON-RPC
- sse: Server-Sent Events
- streamable-http: HTTP with session management and SSE responses
"""

import asyncio
import json
import logging
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union

import aiohttp
from ..core.schemas import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPTransportError(Exception):
    """Base exception for MCP transport errors."""
    def __init__(self, message: str, code: int = -32603):
        self.message = message
        self.code = code
        super().__init__(message)


class MCPTransport(ABC):
    """Abstract base class for MCP transport implementations."""
    
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.capabilities: Dict[str, Any] = {}
        self.server_info: Dict[str, Any] = {}
        self._connected = False
    
    @abstractmethod
    async def initialize(self) -> Dict[str, Any]:
        """Initialize transport and return server capabilities."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from transport."""
        pass
    
    @abstractmethod
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server."""
        pass
    
    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        pass
    
    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._connected


class HTTPTransport(MCPTransport):
    """Standard HTTP transport for MCP servers."""
    
    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self.session: Optional[aiohttp.ClientSession] = None
        self.request_id = 0
        self.base_url = config.url.rstrip('/')
    
    async def initialize(self) -> Dict[str, Any]:
        """Initialize HTTP transport."""
        if self._connected:
            return self.capabilities
            
        # Create HTTP session
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Add custom headers from config
        if hasattr(self.config, 'headers') and self.config.headers:
            headers.update(self.config.headers)
            
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers
        )
        
        # Try standard MCP initialize first
        try:
            return await self._standard_initialize()
        except MCPTransportError as e:
            # If initialize method is not supported, fall back gracefully
            if "Unknown method" in str(e) or "Method not found" in str(e) or e.code == -32601:
                logger.info(f"Server doesn't support initialize method, proceeding with fallback for {self.base_url}")
                return await self._fallback_initialize()
            else:
                # Re-raise other MCP errors
                if self.session:
                    await self.session.close()
                    self.session = None
                raise
        except Exception as e:
            if self.session:
                await self.session.close()
                self.session = None
            raise MCPTransportError(f"Failed to initialize HTTP transport: {str(e)}")
    
    async def _standard_initialize(self) -> Dict[str, Any]:
        """Standard MCP initialize procedure."""
        init_params = {
            "protocolVersion": "2025-01-24",
            "capabilities": {"tools": {}, "sampling": {}},
            "clientInfo": {"name": "workflow-engine", "version": "1.0.0"}
        }
        
        result = await self._make_request('initialize', init_params)
        self.capabilities = result.get('capabilities', {})
        self.server_info = result.get('serverInfo', {})
        self._connected = True
        
        logger.info(f"Initialized HTTP MCP transport to {self.base_url}")
        return result
    
    async def _fallback_initialize(self) -> Dict[str, Any]:
        """Fallback initialization for servers that don't support initialize."""
        # Set basic capabilities and mark as connected
        self.capabilities = {"tools": {}}
        self.server_info = {"name": "unknown", "version": "unknown"}
        self._connected = True
        
        logger.info(f"Fallback initialization complete for HTTP MCP transport to {self.base_url}")
        return {
            "capabilities": self.capabilities,
            "serverInfo": self.server_info
        }
    
    async def disconnect(self) -> None:
        """Disconnect HTTP transport."""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        self._connected = False
        logger.info(f"Disconnected HTTP MCP transport from {self.base_url}")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List tools via HTTP transport."""
        if not self._connected:
            await self.initialize()
            
        result = await self._make_request('tools/list', {})
        return result.get('tools', [])
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call tool via HTTP transport."""
        if not self._connected:
            await self.initialize()
            
        params = {
            'name': tool_name,
            'arguments': arguments
        }
        
        return await self._make_request('tools/call', params)
    
    async def _make_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make JSON-RPC 2.0 request."""
        if not self.session:
            raise MCPTransportError("Not connected to MCP server")
            
        self.request_id += 1
        
        request_data = {
            'jsonrpc': '2.0',
            'id': self.request_id,
            'method': method,
            'params': params
        }
        
        # Use base_url as endpoint since it already includes the MCP path
        endpoint = self.base_url
        logger.debug(f"Making MCP HTTP request to {endpoint}: {method}")
        
        try:
            async with self.session.post(endpoint, json=request_data) as response:
                if response.status != 200:
                    response_text = await response.text()
                    raise MCPTransportError(f"HTTP {response.status}: {response_text}")
                
                response_data = await response.json()
                
                # Check for JSON-RPC error
                if 'error' in response_data and response_data['error'] is not None:
                    error = response_data['error']
                    error_code = error.get('code', -32603)
                    error_message = error.get('message', 'Unknown error')
                    raise MCPTransportError(f"MCP error: {error_message}", error_code)
                
                return response_data.get('result', {})
                
        except aiohttp.ClientError as e:
            raise MCPTransportError(f"HTTP request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise MCPTransportError(f"Invalid JSON response: {str(e)}")


class StreamableHTTPTransport(MCPTransport):
    """Streamable HTTP transport with session management for servers like Jira MCP."""
    
    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self.session: Optional[aiohttp.ClientSession] = None
        self.request_id = 0
        self.base_url = config.url.rstrip('/')
        self.session_id: Optional[str] = None
    
    async def initialize(self) -> Dict[str, Any]:
        """Initialize streamable HTTP transport with session management."""
        if self._connected:
            return self.capabilities
            
        # Create HTTP session with required headers
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream'
        }
        
        # Add custom headers from config
        if hasattr(self.config, 'headers') and self.config.headers:
            headers.update(self.config.headers)
            
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers
        )
        
        # Try standard MCP initialize first
        try:
            return await self._standard_streamable_initialize()
        except MCPTransportError as e:
            # If initialize method is not supported, fall back gracefully
            if "Unknown method" in str(e) or "Method not found" in str(e) or e.code == -32601:
                logger.info(f"Server doesn't support initialize method, proceeding with fallback for {self.base_url}")
                return await self._fallback_streamable_initialize()
            else:
                # Re-raise other MCP errors
                if self.session:
                    await self.session.close()
                    self.session = None
                raise
        except Exception as e:
            if self.session:
                await self.session.close()
                self.session = None
            raise MCPTransportError(f"Failed to initialize streamable HTTP transport: {str(e)}")
    
    async def _standard_streamable_initialize(self) -> Dict[str, Any]:
        """Standard MCP initialize procedure for streamable transport."""
        # Step 1: Initialize MCP session
        init_params = {
            "protocolVersion": "2025-01-24",
            "capabilities": {"tools": {}, "sampling": {}},
            "clientInfo": {"name": "workflow-engine", "version": "1.0.0"}
        }
        
        response = await self._make_request_with_headers('initialize', init_params)
        
        # Step 2: Extract session ID from headers
        if 'headers' in response and 'mcp-session-id' in response['headers']:
            self.session_id = response['headers']['mcp-session-id']
            logger.debug(f"Extracted MCP session ID: {self.session_id}")
        
        # Step 3: Send initialized notification  
        await self._make_notification('notifications/initialized', {})
        
        result = response['data']['result']
        self.capabilities = result.get('capabilities', {})
        self.server_info = result.get('serverInfo', {})
        self._connected = True
        
        logger.info(f"Initialized streamable HTTP MCP transport to {self.base_url} with session {self.session_id}")
        return result
    
    async def _fallback_streamable_initialize(self) -> Dict[str, Any]:
        """Fallback initialization for streamable servers that don't support initialize."""
        # Set basic capabilities and mark as connected
        self.capabilities = {"tools": {}}
        self.server_info = {"name": "unknown", "version": "unknown"}
        self._connected = True
        
        logger.info(f"Fallback initialization complete for streamable HTTP MCP transport to {self.base_url}")
        return {
            "capabilities": self.capabilities,
            "serverInfo": self.server_info
        }
    
    async def disconnect(self) -> None:
        """Disconnect streamable HTTP transport."""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        self.session_id = None
        self._connected = False
        logger.info(f"Disconnected streamable HTTP MCP transport from {self.base_url}")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List tools via streamable HTTP transport."""
        if not self._connected:
            await self.initialize()
            
        result = await self._make_request('tools/list', {})
        return result.get('tools', [])
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call tool via streamable HTTP transport."""
        if not self._connected:
            await self.initialize()
            
        params = {
            'name': tool_name,
            'arguments': arguments
        }
        
        return await self._make_request('tools/call', params)
    
    async def _make_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make request and return result."""
        response = await self._make_request_with_headers(method, params)
        return response['data']['result']
    
    async def _make_request_with_headers(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make JSON-RPC 2.0 request with session support and return data + headers."""
        if not self.session:
            raise MCPTransportError("Not connected to MCP server")
            
        self.request_id += 1
        
        request_data = {
            'jsonrpc': '2.0',
            'id': self.request_id,
            'method': method,
            'params': params
        }
        
        # Append /mcp/ only if the base URL doesn't already end with /mcp
        if self.base_url.rstrip('/').endswith('/mcp'):
            endpoint = f"{self.base_url.rstrip('/')}/"
        else:
            endpoint = f"{self.base_url}/mcp/"
        headers = {}
        
        # Add session ID to headers if available
        if self.session_id:
            headers['mcp-session-id'] = self.session_id
        
        logger.debug(f"Making MCP streamable HTTP request to {endpoint}: {method}")
        
        try:
            async with self.session.post(endpoint, json=request_data, headers=headers) as response:
                if response.status != 200:
                    response_text = await response.text()
                    raise MCPTransportError(f"HTTP {response.status}: {response_text}")
                
                # Handle Server-Sent Events format
                content_type = response.headers.get('content-type', '')
                if 'text/event-stream' in content_type:
                    response_text = await response.text()
                    response_data = self._parse_sse_response(response_text)
                else:
                    response_data = await response.json()
                
                # Check for JSON-RPC error
                if 'error' in response_data and response_data['error'] is not None:
                    error = response_data['error']
                    error_code = error.get('code', -32603)
                    error_message = error.get('message', 'Unknown error')
                    raise MCPTransportError(f"MCP error: {error_message}", error_code)
                
                return {
                    'data': response_data,
                    'headers': dict(response.headers)
                }
                
        except aiohttp.ClientError as e:
            raise MCPTransportError(f"HTTP request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise MCPTransportError(f"Invalid JSON response: {str(e)}")
    
    async def _make_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Make notification request (no ID, no response expected)."""
        if not self.session:
            raise MCPTransportError("Not connected to MCP server")
        
        request_data = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params
        }
        
        # Append /mcp/ only if the base URL doesn't already end with /mcp
        if self.base_url.rstrip('/').endswith('/mcp'):
            endpoint = f"{self.base_url.rstrip('/')}/"
        else:
            endpoint = f"{self.base_url}/mcp/"
        headers = {}
        
        if self.session_id:
            headers['mcp-session-id'] = self.session_id
        
        async with self.session.post(endpoint, json=request_data, headers=headers) as response:
            # Notifications don't expect meaningful responses
            pass
    
    def _parse_sse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse Server-Sent Events response format."""
        lines = response_text.strip().split('\n')
        data_line = next((line for line in lines if line.startswith('data: ')), None)
        
        if data_line:
            json_data = data_line[6:]  # Remove "data: " prefix
            return json.loads(json_data)
        else:
            return {}


class StdioTransport(MCPTransport):
    """Stdio transport for process-based MCP servers."""
    
    def __init__(self, config: MCPServerConfig):
        super().__init__(config)
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 0
    
    async def initialize(self) -> Dict[str, Any]:
        """Initialize stdio transport."""
        if self._connected:
            return self.capabilities
            
        # Start MCP server process
        command = [self.config.command]
        if self.config.args:
            command.extend(self.config.args)
        
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Try standard MCP initialize first
            try:
                return await self._standard_stdio_initialize(command)
            except MCPTransportError as e:
                # If initialize method is not supported, fall back gracefully
                if "Unknown method" in str(e) or "Method not found" in str(e) or e.code == -32601:
                    logger.info(f"Server doesn't support initialize method, proceeding with fallback for stdio: {' '.join(command)}")
                    return await self._fallback_stdio_initialize(command)
                else:
                    # Re-raise other MCP errors
                    raise
            
        except Exception as e:
            if self.process:
                self.process.terminate()
                self.process = None
            raise MCPTransportError(f"Failed to initialize stdio transport: {str(e)}")
    
    async def _standard_stdio_initialize(self, command: List[str]) -> Dict[str, Any]:
        """Standard MCP initialize procedure for stdio transport."""
        init_params = {
            "protocolVersion": "2025-01-24",
            "capabilities": {"tools": {}, "sampling": {}},
            "clientInfo": {"name": "workflow-engine", "version": "1.0.0"}
        }
        
        result = await self._make_request('initialize', init_params)
        self.capabilities = result.get('capabilities', {})
        self.server_info = result.get('serverInfo', {})
        self._connected = True
        
        logger.info(f"Initialized stdio MCP transport: {' '.join(command)}")
        return result
    
    async def _fallback_stdio_initialize(self, command: List[str]) -> Dict[str, Any]:
        """Fallback initialization for stdio servers that don't support initialize."""
        # Set basic capabilities and mark as connected
        self.capabilities = {"tools": {}}
        self.server_info = {"name": "unknown", "version": "unknown"}
        self._connected = True
        
        logger.info(f"Fallback initialization complete for stdio MCP transport: {' '.join(command)}")
        return {
            "capabilities": self.capabilities,
            "serverInfo": self.server_info
        }
    
    async def disconnect(self) -> None:
        """Disconnect stdio transport."""
        if self.process:
            self.process.terminate()
            self.process.wait()
            self.process = None
        self._connected = False
        logger.info("Disconnected stdio MCP transport")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List tools via stdio transport."""
        if not self._connected:
            await self.initialize()
            
        result = await self._make_request('tools/list', {})
        return result.get('tools', [])
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call tool via stdio transport."""
        if not self._connected:
            await self.initialize()
            
        params = {
            'name': tool_name,
            'arguments': arguments
        }
        
        return await self._make_request('tools/call', params)
    
    async def _make_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make JSON-RPC 2.0 request via stdio."""
        if not self.process:
            raise MCPTransportError("Not connected to MCP server process")
            
        self.request_id += 1
        
        request_data = {
            'jsonrpc': '2.0',
            'id': self.request_id,
            'method': method,
            'params': params
        }
        
        try:
            # Send request to process stdin
            request_json = json.dumps(request_data) + '\n'
            self.process.stdin.write(request_json)
            self.process.stdin.flush()
            
            # Read response from process stdout
            response_line = self.process.stdout.readline()
            if not response_line:
                raise MCPTransportError("No response from MCP server process")
            
            response_data = json.loads(response_line.strip())
            
            # Check for JSON-RPC error
            if 'error' in response_data and response_data['error'] is not None:
                error = response_data['error']
                error_code = error.get('code', -32603)
                error_message = error.get('message', 'Unknown error')
                raise MCPTransportError(f"MCP error: {error_message}", error_code)
            
            return response_data.get('result', {})
            
        except json.JSONDecodeError as e:
            raise MCPTransportError(f"Invalid JSON response: {str(e)}")
        except Exception as e:
            raise MCPTransportError(f"Stdio request failed: {str(e)}")


def create_transport(config: MCPServerConfig) -> MCPTransport:
    """Factory function to create appropriate MCP transport."""
    transport_map = {
        "http": HTTPTransport,
        "sse": StreamableHTTPTransport,  # SSE uses streamable HTTP implementation
        "streamable-http": StreamableHTTPTransport,
        "stdio": StdioTransport,
    }
    
    transport_class = transport_map.get(config.type)
    if not transport_class:
        raise MCPTransportError(f"Unsupported transport type: {config.type}")
    
    return transport_class(config)