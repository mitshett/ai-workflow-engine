"""
Simple FastAPI application for the AI Workflow Engine.

This module creates and configures a clean FastAPI application focused
on workflow execution without complex monitoring infrastructure.

Author: AI Workflow Engine Team
"""

import time
from contextlib import asynccontextmanager
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env file from {env_path}")
    else:
        print(f"⚠️  .env file not found at {env_path}")
except ImportError:
    print("⚠️  python-dotenv not installed, .env file won't be loaded")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import utilities
from ..shared.utils.logging import configure_logging, get_logger
from ..shared.utils.correlation_id import correlation_id_middleware
from ..shared.schemas.responses.base import ErrorResponse
from ..domain.exceptions.base import WorkflowEngineException

# Import exception handlers
from .exception_handlers import register_exception_handlers

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Simple application lifespan manager.
    
    Handles basic startup and shutdown procedures.
    """
    startup_start_time = time.time()
    
    # Startup
    logger.info("🚀 AI Workflow Engine starting up...")
    
    try:
        # Configure basic logging
        configure_logging(
            level="INFO",
            json_format=False,
            include_timestamp=True
        )
        
        # Calculate startup duration
        startup_duration = time.time() - startup_start_time
        
        logger.info(
            "✅ AI Workflow Engine startup complete",
            startup_duration_seconds=startup_duration
        )
        
        yield
        
    except Exception as e:
        logger.error(
            "❌ AI Workflow Engine startup failed",
            error=str(e),
            error_type=type(e).__name__
        )
        raise
    
    # Shutdown
    logger.info("🛑 AI Workflow Engine shutting down...")
    logger.info("✅ AI Workflow Engine shutdown complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application instance
    """
    # Create FastAPI app
    app = FastAPI(
        title="AI Workflow Engine",
        description="Workflow orchestration system for AI agents and tools",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify allowed origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add correlation ID middleware
    app.middleware("http")(correlation_id_middleware)
    
    # Add request logging middleware
    app.middleware("http")(request_logging_middleware)
    
    # Add error handling middleware
    app.middleware("http")(error_handling_middleware)
    
    # Register exception handlers
    register_exception_handlers(app)
    
    # Register API routes
    register_routes(app)
    
    return app


async def request_logging_middleware(request: Request, call_next):
    """
    Simple middleware to log HTTP requests.
    """
    start_time = time.time()
    
    # Extract request information
    method = request.method
    url = str(request.url)
    
    # Get correlation ID for tracing
    from ..shared.utils.correlation_id import get_correlation_id
    correlation_id = get_correlation_id()
    
    try:
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        status_code = response.status_code
        
        # Determine log level based on status code
        if status_code >= 500:
            log_level = logger.error
        elif status_code >= 400:
            log_level = logger.warning
        else:
            log_level = logger.info
        
        # Log response
        log_level(
            "HTTP request completed",
            method=method,
            url=url,
            status_code=status_code,
            duration_seconds=round(duration, 3),
            correlation_id=correlation_id,
        )
        
        return response
        
    except Exception as e:
        # Calculate duration for failed requests
        duration = time.time() - start_time
        
        # Log error
        logger.error(
            "HTTP request failed",
            method=method,
            url=url,
            duration_seconds=round(duration, 3),
            error=str(e),
            error_type=type(e).__name__,
            correlation_id=correlation_id
        )
        
        raise


async def error_handling_middleware(request: Request, call_next):
    """
    Simple middleware to handle errors.
    """
    try:
        return await call_next(request)
        
    except WorkflowEngineException as we_error:
        # Handle known application errors
        logger.warning(
            "Application error occurred",
            error=str(we_error),
            error_type=type(we_error).__name__,
            method=request.method,
            url=str(request.url)
        )
        
        # Return structured error response
        from ..shared.utils.correlation_id import get_correlation_id
        
        error_response = ErrorResponse.from_exception(
            we_error,
            correlation_id=get_correlation_id()
        )
        
        return JSONResponse(
            status_code=getattr(we_error, 'status_code', 400),
            content=error_response.model_dump(mode='json')
        )
        
    except Exception as e:
        # Handle unexpected system errors
        logger.error(
            "Unhandled system error in request processing",
            error=str(e),
            error_type=type(e).__name__,
            method=request.method,
            url=str(request.url)
        )
        
        # Return generic error response
        from ..shared.utils.correlation_id import get_correlation_id
        
        error_response = ErrorResponse.from_exception(
            e,
            correlation_id=get_correlation_id()
        )
        
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump(mode='json')
        )


def register_routes(app: FastAPI) -> None:
    """
    Register all API routes with the application.
    """
    # Root endpoint
    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "service": "AI Workflow Engine",
            "version": "0.1.0",
            "description": "Workflow orchestration system for AI agents and tools",
            "docs": "/docs",
            "health": "/health"
        }
    
    # Basic health check endpoint
    @app.get("/health")
    async def health_check():
        """Basic health check endpoint."""
        return {
            "status": "healthy",
            "service": "AI Workflow Engine",
            "version": "0.1.0",
            "timestamp": time.time()
        }
    
    # Simple test endpoint
    @app.get("/test")
    async def test_endpoint():
        """Simple test endpoint to verify API functionality."""
        return {
            "message": "AI Workflow Engine is running!",
            "status": "success",
            "api_version": "v1",
            "endpoints": {
                "execute_workflow": "/api/v1/workflows/execute",
                "health": "/health"
            }
        }
    
    # Include API routers
    try:
        from ..api.v1.execution import router as execution_router
        app.include_router(execution_router, prefix="")  # Router already has prefix
        logger.info("Execution API routes registered successfully")
    except ImportError as e:
        logger.warning(f"Could not import execution router: {e}")


# Create the application instance
app = create_app()