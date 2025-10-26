"""
AI Workflow Engine - Main FastAPI Application

Complete REST API server for the AI Workflow Engine including:
- Workflow validation endpoints
- Workflow execution endpoints  
- Health monitoring and metrics
- Interactive API documentation

Author: AI Workflow Engine Team
"""

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    from pathlib import Path
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not available, skip

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import time
from contextlib import asynccontextmanager

# Import routers
from .validation import router as validation_router
from .execution import router as execution_router

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("AI Workflow Engine API starting up...")
    yield
    # Shutdown
    logger.info("AI Workflow Engine API shutting down...")


# Create FastAPI application
app = FastAPI(
    title="AI Workflow Engine API",
    description="""
    ## AI Workflow Engine - REST API
    
    A comprehensive API for creating, validating, and executing AI-native workflows.
    
    ### Features:
    - **Workflow Validation**: Comprehensive validation with cycle detection and optimization suggestions
    - **Workflow Execution**: Execute workflows with real-time monitoring and detailed results  
    - **Enterprise Ready**: Support for START/END nodes, agent nodes with Azure OpenAI integration
    - **Extensible**: Plugin architecture for custom node types
    
    ### Supported Node Types:
    - `start` - Workflow entry points
    - `end` - Workflow completion points with output collection
    - `agent` - AI agents with Azure OpenAI, Anthropic, OpenAI support
    - `tool` - External tool integrations
    - `mcp_server` - Model Context Protocol server integrations
    - `condition` - Conditional branching logic
    
    ### Authentication:
    For agent nodes using Azure OpenAI, set these environment variables:
    - `AZURE_OPENAI_CLIENT_ID`
    - `AZURE_OPENAI_CLIENT_SECRET` 
    - `AZURE_OPENAI_APP_KEY`
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response middleware for logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing."""
    start_time = time.time()
    
    # Log request
    logger.info(f"Request: {request.method} {request.url.path}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = (time.time() - start_time) * 1000
    
    # Log response
    logger.info(
        f"Response: {request.method} {request.url.path} - "
        f"Status: {response.status_code} - Duration: {duration:.2f}ms"
    )
    
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error_type": type(exc).__name__,
            "path": request.url.path
        }
    )


# Include routers
app.include_router(validation_router)
app.include_router(execution_router)


# Root endpoint
@app.get("/", tags=["root"])
async def root():
    """Root endpoint with API information."""
    return {
        "message": "AI Workflow Engine API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": {
            "validation": "/api/v1/workflows/validate/health",
            "execution": "/api/v1/workflows/health"
        },
        "endpoints": {
            "validate_workflow": "POST /api/v1/workflows/validate",
            "execute_workflow": "POST /api/v1/workflows/execute",
            "get_execution": "GET /api/v1/workflows/executions/{run_id}",
            "list_executions": "GET /api/v1/workflows/executions"
        }
    }


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check():
    """Overall system health check."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {
            "validation": "healthy", 
            "execution": "healthy"
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting AI Workflow Engine API Server")
    print("=" * 50)
    print("📖 API Documentation: http://localhost:8000/docs")
    print("🔍 Alternative Docs: http://localhost:8000/redoc") 
    print("❤️  Health Check: http://localhost:8000/health")
    print("🔧 Validation Health: http://localhost:8000/api/v1/workflows/validate/health")
    print("⚡ Execution Health: http://localhost:8000/api/v1/workflows/health")
    print("=" * 50)
    
    uvicorn.run(
        "workflow_engine.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )