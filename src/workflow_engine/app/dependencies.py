"""
Global dependency injection setup for the AI Workflow Engine.

This module provides dependency injection setup using FastAPI's built-in
dependency system, ensuring consistent service instantiation across the application.

Author: AI Workflow Engine Team
"""

from typing import AsyncGenerator, Optional
from fastapi import Depends, HTTPException, Request

# Import utilities
from ..shared.utils.correlation_id import (
    extract_correlation_id_from_request,
    get_correlation_id,
    set_correlation_id
)
from ..shared.utils.logging import get_logger


logger = get_logger(__name__)


async def get_correlation_id_dependency(request: Request) -> str:
    """
    FastAPI dependency to extract and set correlation ID.
    
    This dependency extracts the correlation ID from the request
    and sets it in the context for the duration of the request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Correlation ID string
    """
    correlation_id = extract_correlation_id_from_request(request)
    set_correlation_id(correlation_id)
    return correlation_id


async def get_request_logger(
    correlation_id: str = Depends(get_correlation_id_dependency)
):
    """
    FastAPI dependency to get a logger with correlation ID context.
    
    Args:
        correlation_id: Correlation ID from dependency
        
    Returns:
        Logger instance with correlation ID context
    """
    import logging
    return logging.getLogger("request")




# Service dependencies - CLEAN ARCHITECTURE WITH DEPENDENCY INJECTION
async def get_validation_service():
    """
    FastAPI dependency for validation service.
    
    Returns:
        ValidationService instance
    """
    from ..services import ValidationService
    return ValidationService()


async def get_executor_registry_service():
    """
    FastAPI dependency for node executor registry service.
    
    Returns:
        NodeExecutorRegistryService instance
    """
    from ..services import NodeExecutorRegistryService
    service = NodeExecutorRegistryService()
    await service.initialize()  # Initialize executors on first use
    return service


async def get_execution_service(
    executor_registry_service = Depends(get_executor_registry_service)
):
    """
    FastAPI dependency for execution service.
    
    Args:
        executor_registry_service: NodeExecutorRegistryService dependency
    
    Returns:
        ExecutionService instance with proper dependencies
    """
    from ..services import ExecutionService
    return ExecutionService(
        executor_registry_service=executor_registry_service,
        max_parallel_nodes=10,
        default_timeout_seconds=300
    )


async def get_workflow_service(
    execution_service = Depends(get_execution_service),
    validation_service = Depends(get_validation_service)
):
    """
    FastAPI dependency for workflow service with proper dependency injection.
    
    This creates a WorkflowService with all required dependencies,
    following the clean architecture pattern.
    
    Args:
        execution_service: ExecutionService dependency
        validation_service: ValidationService dependency
        
    Returns:
        WorkflowService instance with injected dependencies
    """
    from ..services import WorkflowService
    
    # No database repository needed
    return WorkflowService(
        execution_service=execution_service,
        validation_service=validation_service,
        workflow_repository=None  # No persistence needed
    )


async def get_response_service():
    """
    FastAPI dependency for response service.
    
    This provides the centralized response transformation service
    that eliminates code duplication across the API layer.
    
    Returns:
        ResponseService instance
    """
    from ..services import ResponseService
    return ResponseService()


async def get_orchestration_service(
    workflow_service = Depends(get_workflow_service),
    execution_service = Depends(get_execution_service),
    validation_service = Depends(get_validation_service),
    response_service = Depends(get_response_service),
    executor_registry_service = Depends(get_executor_registry_service)
):
    """
    FastAPI dependency for workflow orchestration service.
    
    This provides the high-level orchestration service that coordinates
    all workflow operations with proper dependency injection.
    
    Args:
        workflow_service: WorkflowService dependency
        execution_service: ExecutionService dependency
        validation_service: ValidationService dependency
        response_service: ResponseService dependency
        executor_registry_service: NodeExecutorRegistryService dependency
        
    Returns:
        WorkflowOrchestrationService instance with all dependencies
    """
    from ..services import WorkflowOrchestrationService
    return WorkflowOrchestrationService(
        workflow_service=workflow_service,
        execution_service=execution_service,
        validation_service=validation_service,
        response_service=response_service,
        executor_registry_service=executor_registry_service
    )


# Repository dependencies - IN-MEMORY ONLY (NO DATABASE)
async def get_workflow_repository():
    """
    FastAPI dependency for workflow repository.
    
    Returns in-memory repository since we're not using database persistence.
    
    Returns:
        In-memory workflow repository instance
    """
    # Simple in-memory repository - no database needed
    return None  # No persistence needed for now




# Authentication and authorization dependencies
async def get_current_user(request: Request) -> Optional[dict]:
    """
    FastAPI dependency for getting current user.
    
    This is a placeholder for future authentication implementation.
    For now, it returns None (no authentication required).
    
    Args:
        request: FastAPI request object
        
    Returns:
        User information or None
    """
    # TODO: Implement authentication when security layer is added
    return None


async def require_authentication(
    current_user: Optional[dict] = Depends(get_current_user)
) -> dict:
    """
    FastAPI dependency that requires authentication.
    
    This dependency ensures that the current user is authenticated
    before allowing access to protected endpoints.
    
    Args:
        current_user: Current user from dependency
        
    Returns:
        Authenticated user information
        
    Raises:
        HTTPException: If user is not authenticated
    """
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )
    return current_user




# Request validation dependencies
def validate_request_size(max_size: int = 10 * 1024 * 1024):  # 10MB default
    """
    FastAPI dependency factory for request size validation.
    
    Creates a dependency that validates the request size is within limits.
    
    Args:
        max_size: Maximum allowed request size in bytes
        
    Returns:
        Dependency function
    """
    async def validate_size(request: Request):
        """Validate request size."""
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"Request size too large. Maximum allowed: {max_size} bytes"
            )
        return True
    
    return validate_size


def validate_content_type(allowed_types: list = None):
    """
    FastAPI dependency factory for content type validation.
    
    Creates a dependency that validates the request content type.
    
    Args:
        allowed_types: List of allowed content types
        
    Returns:
        Dependency function
    """
    if allowed_types is None:
        allowed_types = ['application/json']
    
    async def validate_type(request: Request):
        """Validate content type."""
        content_type = request.headers.get('content-type', '')
        if not any(allowed_type in content_type for allowed_type in allowed_types):
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported content type. Allowed: {allowed_types}"
            )
        return True
    
    return validate_type


# Rate limiting dependencies
def rate_limit(requests_per_minute: int = 60):
    """
    FastAPI dependency factory for rate limiting.
    
    Creates a dependency that implements rate limiting per client.
    This is a placeholder implementation.
    
    Args:
        requests_per_minute: Maximum requests per minute per client
        
    Returns:
        Dependency function
    """
    async def check_rate_limit(request: Request):
        """Check rate limit for client."""
        # TODO: Implement actual rate limiting logic
        # For now, just log the request
        client_ip = request.client.host if request.client else "unknown"
        logger.debug(
            "Rate limit check",
            client_ip=client_ip,
            requests_per_minute=requests_per_minute
        )
        return True
    
    return check_rate_limit