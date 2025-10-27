"""
Base response schemas for the AI Workflow Engine API.

This module provides standardized response formats that ensure consistency
across all API endpoints. All API responses should inherit from these base classes.

Author: AI Workflow Engine Team
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """
    Standard API response wrapper for all endpoints.
    
    This base class ensures consistent response format across the entire API,
    including success status, optional messages, timestamps, and correlation IDs
    for request tracing.
    
    Attributes:
        success: Boolean indicating if the request was successful
        message: Optional human-readable message
        timestamp: UTC timestamp when the response was generated
        correlation_id: Optional request correlation ID for tracing
    """
    
    success: bool = Field(
        ..., 
        description="Whether the request was successful"
    )
    message: Optional[str] = Field(
        None, 
        description="Optional human-readable message"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when response was generated"
    )
    correlation_id: Optional[str] = Field(
        None,
        description="Request correlation ID for tracing"
    )

    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat() + "Z"
        }
    }


class BaseDataResponse(BaseResponse):
    """
    Response wrapper that includes a data payload.
    
    This class extends BaseResponse to include a data field for responses
    that need to return structured data along with the standard metadata.
    
    Attributes:
        data: The actual response payload
    """
    
    data: Any = Field(
        ...,
        description="Response data payload"
    )


class BaseListResponse(BaseResponse):
    """
    Response wrapper for paginated list endpoints.
    
    This class provides a standard format for list responses with pagination
    metadata, ensuring consistent behavior across all list endpoints.
    
    Attributes:
        data: List of items
        total_count: Total number of items (before pagination)
        page: Current page number (1-based)
        page_size: Number of items per page
        has_more: Whether more pages are available
    """
    
    data: list = Field(
        ...,
        description="List of items"
    )
    total_count: int = Field(
        ...,
        description="Total number of items available"
    )
    page: int = Field(
        1,
        ge=1,
        description="Current page number (1-based)"
    )
    page_size: int = Field(
        50,
        ge=1,
        le=1000,
        description="Number of items per page"
    )
    has_more: bool = Field(
        ...,
        description="Whether more pages are available"
    )


class ErrorDetail(BaseModel):
    """
    Structured error information.
    
    Provides detailed error information including error codes,
    messages, and additional context for debugging.
    
    Attributes:
        code: Machine-readable error code
        message: Human-readable error message
        field: Optional field name if error is field-specific
        details: Additional error context
    """
    
    code: str = Field(
        ...,
        description="Machine-readable error code"
    )
    message: str = Field(
        ...,
        description="Human-readable error message"
    )
    field: Optional[str] = Field(
        None,
        description="Field name if error is field-specific"
    )
    details: Optional[dict] = Field(
        None,
        description="Additional error context"
    )


class ErrorResponse(BaseResponse):
    """
    Standardized error response format.
    
    This class provides a consistent format for all error responses,
    including detailed error information and debugging context.
    
    Attributes:
        error: Detailed error information
    """
    
    success: bool = Field(
        False,
        description="Always False for error responses"
    )
    error: ErrorDetail = Field(
        ...,
        description="Detailed error information"
    )

    @classmethod
    def from_exception(
        cls, 
        exc: Exception, 
        correlation_id: Optional[str] = None
    ) -> "ErrorResponse":
        """
        Create an ErrorResponse from an exception.
        
        Args:
            exc: The exception to convert
            correlation_id: Optional correlation ID
            
        Returns:
            ErrorResponse: Standardized error response
        """
        # Import here to avoid circular imports
        from ....domain.exceptions.base import WorkflowEngineException
        
        if isinstance(exc, WorkflowEngineException):
            error_detail = ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details
            )
        else:
            error_detail = ErrorDetail(
                code="INTERNAL_ERROR",
                message=str(exc),
                details={"exception_type": type(exc).__name__}
            )
        
        return cls(
            error=error_detail,
            correlation_id=correlation_id
        )