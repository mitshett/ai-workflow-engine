# Cisco MCP Server

Simple standalone MCP server exposing Cisco Software Insights tools via HTTP endpoints.

## Features

- 🔐 **OAuth Authentication** - Test Cisco API credentials
- 📦 **Software Suggestions** - Get recommended software for Cisco products  
- 🛡️ **Security Advisories** - Get security advisories by OS type/version
- 🐛 **Bug Information** - Get known bugs for products and versions
- 📋 **Advisory Details** - Get detailed security advisory information

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Credentials
```bash
cp .env.sample .env
# Edit .env with your Cisco API credentials
```

### 3. Start Server
```bash
python main.py
```

Server runs at: http://localhost:8080

## Usage Examples

### Health Check
```bash
curl http://localhost:8080/health
```

### Test Authentication
```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_oauth_token",
      "arguments": {}
    }
  }'
```

### Get Software Suggestions
```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", 
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get_software_suggestions",
      "arguments": {
        "product_id": "WS-C3850-24T-E"
      }
    }
  }'
```

### Get Security Advisories
```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3, 
    "method": "tools/call",
    "params": {
      "name": "get_security_advisories",
      "arguments": {
        "os_type": "iosxe",
        "version": "17.3.4"
      }
    }
  }'
```

## Claude Desktop Integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cisco-tools": {
      "command": "python",
      "args": ["/path/to/cisco-mcp-server/main.py"]
    }
  }
}
```

## API Endpoints

- `GET /` - Server information
- `GET /health` - Health check
- `GET /capabilities` - MCP capabilities
- `POST /mcp` - Main MCP protocol endpoint

## Available Tools

1. **get_oauth_token** - Test API authentication
2. **get_software_suggestions** - Get software recommendations
3. **get_security_advisories** - Get security advisories  
4. **get_bugs** - Get known bugs
5. **get_advisory_details** - Get detailed advisory info

## Requirements

- Python 3.8+
- Cisco API credentials from https://apiconsole.cisco.com/
- FastAPI, aiohttp, uvicorn

## Environment Variables

Required:
- `CISCO_CLIENT_ID` - Your Cisco API client ID
- `CISCO_CLIENT_SECRET` - Your Cisco API client secret

Optional:
- `CISCO_BASE_URL` - Override API base URL
- `CISCO_AUTH_URL` - Override auth URL