"""
Simple Cisco MCP Server
A standalone FastAPI server that exposes Cisco Software Insights tools via MCP protocol
"""

import os
import asyncio
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import logging

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available, use environment variables directly
    pass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== CISCO API CLIENT =====

class CiscoAPIError(Exception):
    """Base exception for Cisco API errors"""
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

class CiscoAPIClient:
    """Simple Cisco API client"""
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://apix.cisco.com"
        self.auth_url = "https://id.cisco.com/oauth2/default/v1/token"
        self.session: Optional[aiohttp.ClientSession] = None
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        
        # API endpoints
        self.endpoints = {
            'suggestions': '/software/suggestion/v2/suggestions/software/productIds/{product_id}',
            'advisories': '/security/advisories/v2/OSType/{os_type}',
            'bugs': '/bug/v3.0/bugs/products/product_id/{product_id}/software_releases/{version}',
            'advisory_by_id': '/security/advisories/v2/advisory/{advisory_id}'
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def _get_access_token(self) -> str:
        """Get valid access token"""
        # Check if token is still valid
        if (self.access_token and self.token_expires_at and 
            datetime.now(timezone.utc) < self.token_expires_at):
            return self.access_token
        
        # Request new token
        logger.info("Requesting new access token")
        session = await self._get_session()
        
        payload = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        try:
            async with session.post(self.auth_url, data=payload, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise CiscoAPIError(f"Token request failed: {response.status} - {error_text}")
                
                token_data = await response.json()
                self.access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 3600)
                
                # Set expiration with 60 second buffer
                self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
                
                logger.info("Access token retrieved successfully")
                return self.access_token
                
        except aiohttp.ClientError as e:
            raise CiscoAPIError(f"Token request failed: {str(e)}")
    
    async def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make authenticated API request"""
        access_token = await self._get_access_token()
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {access_token}',
            'User-Agent': 'CiscoMCPServer/1.0'
        }
        
        url = f"{self.base_url}{endpoint}"
        session = await self._get_session()
        
        logger.info(f"Making {method} request to {url}")
        
        try:
            async with session.request(method, url, params=params, headers=headers) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError:
                        return {'raw_response': response_text}
                
                elif response.status == 401:
                    # Clear token and raise error
                    self.access_token = None
                    self.token_expires_at = None
                    raise CiscoAPIError(f"Authentication failed: {response_text}", response.status)
                
                else:
                    raise CiscoAPIError(f"API call failed: {response.status} - {response_text}", response.status)
        
        except aiohttp.ClientError as e:
            raise CiscoAPIError(f"Network error: {str(e)}")
    
    async def close(self):
        """Clean up resources"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    # ===== MCP TOOL METHODS =====
    
    async def get_oauth_token(self) -> Dict[str, Any]:
        """Test authentication and get token info"""
        try:
            token = await self._get_access_token()
            return {
                "success": True,
                "message": "Token retrieved successfully",
                "token_preview": f"{token[:20]}...",
                "expires_at": self.token_expires_at.isoformat() if self.token_expires_at else None
            }
        except Exception as e:
            logger.error(f"Token test failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_software_suggestions(self, product_id: str) -> Dict[str, Any]:
        """Get software suggestions for a Cisco product"""
        try:
            # Ensure authentication is established
            auth_result = await self.get_oauth_token()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error', 'Unknown error')}",
                    "product_id": product_id
                }
            
            endpoint = self.endpoints['suggestions'].format(product_id=product_id)
            result = await self._make_request('GET', endpoint)
            
            # Transform the data
            transformed = self._transform_suggestions(result, product_id)
            
            return {
                "success": True,
                "data": transformed,
                "metadata": {
                    "product_id": product_id,
                    "retrieved_at": datetime.now(timezone.utc).isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get suggestions for {product_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "product_id": product_id
            }
    
    async def get_security_advisories(self, os_type: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Get security advisories for OS type and version"""
        try:
            # Ensure authentication is established
            auth_result = await self.get_oauth_token()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error', 'Unknown error')}",
                    "os_type": os_type,
                    "version": version
                }
            
            endpoint = self.endpoints['advisories'].format(os_type=os_type)
            params = {}
            if version:
                params['version'] = version
            
            result = await self._make_request('GET', endpoint, params=params)
            
            # Transform the data
            transformed = self._transform_advisories(result, os_type, version)
            
            return {
                "success": True,
                "data": transformed,
                "metadata": {
                    "os_type": os_type,
                    "version": version,
                    "retrieved_at": datetime.now(timezone.utc).isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get advisories for {os_type}: {e}")
            return {
                "success": False,
                "error": str(e),
                "os_type": os_type,
                "version": version
            }
    
    async def get_bugs(self, products: list, status: str = "O", max_pages: int = 5) -> Dict[str, Any]:
        """Get bugs for one or more product/version pairs.
        
        Args:
            products: List of dicts with 'product_id' and 'version' keys.
                      Also accepts a JSON string (from template resolution).
            status: Bug status filter (default 'O' for Open)
            max_pages: Max pages to retrieve per product/version pair
        """
        try:
            # Handle JSON string input (from template resolution)
            if isinstance(products, str):
                try:
                    products = json.loads(products)
                except (json.JSONDecodeError, TypeError):
                    return {
                        "success": False,
                        "error": f"Invalid products format: expected JSON array, got string: {products[:200]}"
                    }
            
            if not isinstance(products, list) or len(products) == 0:
                return {
                    "success": False,
                    "error": "products must be a non-empty array of {product_id, version} objects"
                }
            
            # Coerce argument types (MCP JSON may deliver these as strings)
            try:
                max_pages = int(max_pages)
            except (TypeError, ValueError):
                max_pages = 5
            status = str(status) if status else "O"
            
            # Ensure authentication is established
            auth_result = await self.get_oauth_token()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error', 'Unknown error')}"
                }
            
            results_by_product = []
            
            for item in products:
                product_id = item.get('product_id', '')
                version = item.get('version', '')
                
                if not product_id or not version:
                    results_by_product.append({
                        "product_id": product_id,
                        "version": version,
                        "error": "Missing product_id or version",
                        "bugs": []
                    })
                    continue
                
                all_bugs = []
                page_index = 1
                
                endpoint = self.endpoints['bugs'].format(product_id=product_id, version=version)
                
                try:
                    while page_index <= max_pages:
                        params = {
                            'page_index': page_index,
                            'status': status
                        }
                        
                        result = await self._make_request('GET', endpoint, params=params)
                        
                        page_bugs = result.get('bugs', [])
                        if not page_bugs:
                            break
                        
                        all_bugs.extend(page_bugs)
                        
                        # Check pagination
                        pagination = result.get('pagination', {})
                        total_pages = pagination.get('total_pages', 1)
                        
                        if page_index >= total_pages:
                            break
                        
                        page_index += 1
                    
                    transformed = self._transform_bugs(all_bugs, product_id, version, status)
                    results_by_product.append(transformed)
                    
                except Exception as e:
                    logger.error(f"Failed to get bugs for {product_id} v{version}: {e}")
                    results_by_product.append({
                        "product_id": product_id,
                        "version": version,
                        "error": str(e),
                        "bugs": []
                    })
            
            return {
                "success": True,
                "data": results_by_product,
                "metadata": {
                    "total_products_queried": len(products),
                    "status_filter": status,
                    "retrieved_at": datetime.now(timezone.utc).isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get bugs: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_advisory_details(self, advisory_id: str) -> Dict[str, Any]:
        """Get detailed advisory information"""
        try:
            # Ensure authentication is established
            auth_result = await self.get_oauth_token()
            if not auth_result.get("success"):
                return {
                    "success": False,
                    "error": f"Authentication failed: {auth_result.get('error', 'Unknown error')}",
                    "advisory_id": advisory_id
                }
            
            endpoint = self.endpoints['advisory_by_id'].format(advisory_id=advisory_id)
            result = await self._make_request('GET', endpoint)
            
            return {
                "success": True,
                "data": result,
                "metadata": {
                    "advisory_id": advisory_id,
                    "retrieved_at": datetime.now(timezone.utc).isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get advisory details for {advisory_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "advisory_id": advisory_id
            }
    
    # ===== DATA TRANSFORMATION =====
    
    def _transform_suggestions(self, raw_data: Dict, product_id: str) -> Dict:
        """Transform suggestions data"""
        product_list = raw_data.get('productList', [])
        if not product_list:
            return {
                "product_id": product_id,
                "suggestions": []
            }
        
        product_data = product_list[0]
        product_info = product_data.get('product', {})
        resolved_product_id = product_info.get('basePID') or product_id
        suggestions = []
        
        for suggestion in product_data.get('suggestions', []):
            suggestions.append({
                "product_id": resolved_product_id,
                "version": suggestion.get('releaseFormat1') or suggestion.get('releaseFormat2'),
                "release_date": suggestion.get('releaseDate'),
                "lifecycle": suggestion.get('releaseLifeCycle'),
                "is_suggested": suggestion.get('isSuggested') == 'Y',
                "display_name": suggestion.get('relDispName')
            })
        
        return {
            "product_id": resolved_product_id,
            "product_name": product_info.get('productName'),
            "suggestions": suggestions
        }
    
    def _transform_advisories(self, raw_data: Dict, os_type: str, version: Optional[str]) -> Dict:
        """Transform advisories data"""
        advisories = []
        
        for advisory in raw_data.get('advisories', []):
            advisories.append({
                "advisory_id": advisory.get('advisoryId'),
                "title": advisory.get('advisoryTitle'),
                "cvss_score": float(advisory.get('cvssBaseScore', 0)),
                "severity": advisory.get('sir'),
                "cves": advisory.get('cves', []),
                "publication_date": advisory.get('firstPublished'),
                "status": advisory.get('status')
            })
        
        return {
            "os_type": os_type,
            "version": version,
            "advisories": advisories
        }
    
    def _transform_bugs(self, raw_bugs: List[Dict], product_id: str, version: str, status: str) -> Dict:
        """Transform bugs data"""
        bugs = []
        
        for bug in raw_bugs:
            bugs.append({
                "bug_id": bug.get('bug_id'),
                "headline": bug.get('headline'),
                "description": bug.get('description'),
                "severity": bug.get('severity'),
                "status": bug.get('status'),
                "last_modified": bug.get('last_modified_date')
            })
        
        return {
            "product_id": product_id,
            "version": version,
            "bugs": bugs
        }

# ===== FASTAPI SERVER =====

# FastAPI app
app = FastAPI(
    title="Cisco MCP Server",
    description="Simple MCP server exposing Cisco Software Insights tools",
    version="1.0.0"
)

# Global Cisco client
cisco_client: Optional[CiscoAPIClient] = None

# MCP Protocol Models
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Any
    method: str
    params: Optional[Dict[str, Any]] = None

class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Any
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

@app.on_event("startup")
async def startup_event():
    """Initialize Cisco client"""
    global cisco_client
    
    client_id = os.getenv("CISCO_CLIENT_ID")
    client_secret = os.getenv("CISCO_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        logger.warning("CISCO_CLIENT_ID or CISCO_CLIENT_SECRET not set")
        client_id = client_id or "placeholder"
        client_secret = client_secret or "placeholder"
    
    cisco_client = CiscoAPIClient(client_id, client_secret)
    logger.info("🚀 Cisco MCP Server started")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global cisco_client
    if cisco_client:
        await cisco_client.close()

def get_available_tools() -> List[Dict[str, Any]]:
    """Get available MCP tools"""
    return [
        {
            "name": "get_oauth_token",
            "description": "Test Cisco API authentication",
            "inputSchema": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "get_software_suggestions", 
            "description": "Get software recommendations for Cisco products",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Product ID (e.g., 'WS-C3850-24T-E')"}
                },
                "required": ["product_id"]
            }
        },
        {
            "name": "get_security_advisories",
            "description": "Get security advisories for OS types",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "os_type": {"type": "string", "description": "OS type (e.g., 'iosxe', 'ios')"},
                    "version": {"type": "string", "description": "Optional version"}
                },
                "required": ["os_type"]
            }
        },
        {
            "name": "get_bugs",
            "description": "Get known bugs for one or more product/version pairs",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "products": {
                        "type": "array",
                        "description": "Array of product/version pairs to query bugs for",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "string", "description": "Product ID (e.g., 'ASR1001-X')"},
                                "version": {"type": "string", "description": "Software version (e.g., '16.12.14')"}
                            },
                            "required": ["product_id", "version"]
                        }
                    },
                    "status": {"type": "string", "description": "Bug status filter (default 'O' for Open)", "default": "O"},
                    "max_pages": {"type": "integer", "description": "Max pages per product/version pair", "default": 5}
                },
                "required": ["products"]
            }
        },
        {
            "name": "get_advisory_details",
            "description": "Get detailed advisory information",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "advisory_id": {"type": "string", "description": "Advisory ID"}
                },
                "required": ["advisory_id"]
            }
        }
    ]

async def call_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call a Cisco tool"""
    if not cisco_client:
        raise HTTPException(status_code=500, detail="Client not initialized")
    
    if tool_name == "get_oauth_token":
        return await cisco_client.get_oauth_token()
    elif tool_name == "get_software_suggestions":
        return await cisco_client.get_software_suggestions(arguments["product_id"])
    elif tool_name == "get_security_advisories":
        return await cisco_client.get_security_advisories(
            arguments["os_type"], arguments.get("version")
        )
    elif tool_name == "get_bugs":
        return await cisco_client.get_bugs(
            arguments["products"],
            arguments.get("status", "O"),
            arguments.get("max_pages", 5)
        )
    elif tool_name == "get_advisory_details":
        return await cisco_client.get_advisory_details(arguments["advisory_id"])
    else:
        raise ValueError(f"Unknown tool: {tool_name}")

# ===== MCP ENDPOINTS =====

@app.post("/mcp")
@app.post("/mcp/")
async def mcp_endpoint(request: MCPRequest):
    """Main MCP protocol endpoint"""
    try:
        if request.method == "capabilities":
            # Return server capabilities for MCP client handshake
            return MCPResponse(id=request.id, result={
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cisco-mcp-server", "version": "1.0.0"}
            })
        
        elif request.method == "tools/list":
            return MCPResponse(id=request.id, result={"tools": get_available_tools()})
        
        elif request.method == "tools/call":
            if not request.params:
                raise ValueError("params required")
            
            tool_name = request.params.get("name")
            arguments = request.params.get("arguments", {})
            
            result = await call_tool(tool_name, arguments)
            return MCPResponse(id=request.id, result=result)
        
        else:
            raise ValueError(f"Unknown method: {request.method}")
    
    except Exception as e:
        return MCPResponse(
            id=request.id,
            error={"code": -32603, "message": str(e)}
        )

@app.get("/capabilities")
async def get_capabilities():
    """Get server capabilities"""
    return {
        "server": {"name": "cisco-mcp-server", "version": "1.0.0"},
        "capabilities": {"tools": {}},
        "tools": get_available_tools()
    }

@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "tools_available": len(get_available_tools())
    }

@app.get("/")
async def root():
    """Server info"""
    return {
        "name": "Cisco MCP Server",
        "version": "1.0.0", 
        "description": "Simple MCP server for Cisco Software Insights",
        "mcp_endpoint": "/mcp",
        "capabilities": "/capabilities",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting Cisco MCP Server...")
    print("📡 Server: http://localhost:8080")
    print("💚 Health: http://localhost:8080/health")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)