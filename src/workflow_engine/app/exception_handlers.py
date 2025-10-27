"""
Exception handlers for the AI Workflow Engine FastAPI application.

This module provides centralized exception handling for all custom exceptions,
ensuring consistent error responses across the API.

Author: AI Workflow Engine Team
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..shared.utils.logging import get_logger
from ..shared.utils.correlation_id import get_correlation_id
from ..shared.schemas.responses.base import ErrorResponse, ErrorDetail
from ..domain.exceptions.base import (
    WorkflowEngineException,
    ValidationException,
    ExecutionException,
    ConfigurationException,
    ExternalServiceException,
    BusinessLogicException,
    ResourceNotFoundException,
    PermissionDeniedException
)

logger = get_logger(__name__)


async def workflow_engine_exception_handler(
    request: Request, 
    exc: WorkflowEngineException
) -> JSONResponse:
    """
    Handle custom WorkflowEngineException and its subclasses.
    
    Args:
        request: FastAPI request object
        exc: The exception that was raised
        
    Returns:
        JSONResponse with structured error information
    """
    logger.error(
        "Workflow engine exception occurred",
        error_code=exc.code,
        error_message=exc.message,
        error_details=exc.details,
        exception_type=type(exc).__name__,
        method=request.method,
        url=str(request.url)
    )
    
    # Determine appropriate HTTP status code based on exception type
    status_code_mapping = {
        ValidationException: 400,
        BusinessLogicException: 400,
        ResourceNotFoundException: 404,
        PermissionDeniedException: 403,
        ConfigurationException: 500,
        ExecutionException: 500,
        ExternalServiceException: 502,
        WorkflowEngineException: 500  # Default for base class
    }
    
    status_code = status_code_mapping.get(type(exc), 500)
    
    error_response = ErrorResponse.from_exception(
        exc,
        correlation_id=get_correlation_id()
    )
    
    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(mode='json')
    )


async def validation_error_handler(
    request: Request,
    exc: ValidationError
) -> JSONResponse:
    """
    Handle Pydantic ValidationError exceptions.
    
    Args:
        request: FastAPI request object
        exc: The validation error that was raised
        
    Returns:
        JSONResponse with validation error details
    """
    logger.warning(
        "Request validation failed",
        validation_errors=exc.errors(),
        method=request.method,
        url=str(request.url)
    )
    
    # Format validation errors for user-friendly response
    error_details = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error["loc"])
        error_details.append({
            "field": field_path,
            "message": error["msg"],
            "type": error["type"],
            "input": error.get("input")
        })
    
    error_response = ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details={
                "validation_errors": error_details,
                "error_count": len(error_details)
            }
        ),
        correlation_id=get_correlation_id()
    )
    
    return JSONResponse(
        status_code=422,
        content=error_response.model_dump(mode='json')
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException
) -> JSONResponse:
    """
    Handle FastAPI HTTPException.
    
    Args:
        request: FastAPI request object
        exc: The HTTP exception that was raised
        
    Returns:
        JSONResponse with HTTP error details
    """
    logger.warning(
        "HTTP exception occurred",
        status_code=exc.status_code,
        detail=exc.detail,
        method=request.method,
        url=str(request.url)
    )
    
    # Map HTTP status codes to error codes
    error_code_mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "UNPROCESSABLE_ENTITY",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT"
    }
    
    error_code = error_code_mapping.get(exc.status_code, "HTTP_ERROR")
    
    error_response = ErrorResponse(
        error=ErrorDetail(
            code=error_code,
            message=str(exc.detail),
            details={
                "status_code": exc.status_code,
                "headers": dict(exc.headers) if exc.headers else None
            }
        ),
        correlation_id=get_correlation_id()
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(mode='json')
    )


async def generic_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """
    Handle any unhandled exceptions.
    
    Args:
        request: FastAPI request object
        exc: The generic exception that was raised
        
    Returns:
        JSONResponse with generic error response
    """
    logger.error(
        "Unhandled exception occurred",
        error=str(exc),
        error_type=type(exc).__name__,
        method=request.method,
        url=str(request.url),
        exc_info=True
    )
    
    error_response = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_ERROR",
            message="An internal server error occurred",
            details={
                "exception_type": type(exc).__name__,
                "error_message": str(exc)
            }
        ),
        correlation_id=get_correlation_id()
    )
    
    return JSONResponse(
        status_code=500,
        content=error_response.model_dump(mode='json')
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI application.
    
    Args:
        app: FastAPI application instance
    """
    # Register custom exception handlers
    app.add_exception_handler(WorkflowEngineException, workflow_engine_exception_handler)
    app.add_exception_handler(ValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    
    logger.info("Exception handlers registered successfully")