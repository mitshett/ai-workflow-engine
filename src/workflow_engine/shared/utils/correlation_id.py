"""
Correlation ID utilities for request tracing.

This module provides utilities for generating, managing, and propagating
correlation IDs throughout the application for request tracing and debugging.

Author: AI Workflow Engine Team
"""

import uuid
from typing import Optional
from contextvars import ContextVar
from fastapi import Request, Response


# Context variable to store correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


def generate_correlation_id() -> str:
    """
    Generate a new correlation ID.
    
    Returns:
        A new UUID-based correlation ID
    """
    return str(uuid.uuid4())


def get_correlation_id() -> Optional[str]:
    """
    Get the current correlation ID from context.
    
    Returns:
        The current correlation ID or None if not set
    """
    return correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """
    Set the correlation ID in the current context.
    
    Args:
        correlation_id: The correlation ID to set
    """
    correlation_id_var.set(correlation_id)


def extract_correlation_id_from_request(request: Request) -> str:
    """
    Extract or generate correlation ID from HTTP request.
    
    This function looks for correlation ID in various places:
    1. X-Correlation-ID header
    2. X-Request-ID header  
    3. Generates new one if not found
    
    Args:
        request: FastAPI request object
        
    Returns:
        Correlation ID string
    """
    # Try various header names
    header_names = [
        'X-Correlation-ID',
        'X-Request-ID',
        'X-Trace-ID',
        'Correlation-ID',
        'Request-ID'
    ]
    
    for header_name in header_names:
        correlation_id = request.headers.get(header_name)
        if correlation_id:
            return correlation_id
    
    # Generate new correlation ID if not found
    return generate_correlation_id()


def add_correlation_id_to_response(response: Response, correlation_id: str) -> None:
    """
    Add correlation ID to HTTP response headers.
    
    Args:
        response: FastAPI response object
        correlation_id: Correlation ID to add
    """
    response.headers['X-Correlation-ID'] = correlation_id
    response.headers['X-Request-ID'] = correlation_id


class CorrelationIdManager:
    """
    Context manager for correlation ID lifecycle.
    
    This class provides a context manager interface for managing
    correlation IDs within a specific scope, ensuring proper cleanup.
    """
    
    def __init__(self, correlation_id: Optional[str] = None):
        """
        Initialize correlation ID manager.
        
        Args:
            correlation_id: Optional correlation ID, generates new one if None
        """
        self.correlation_id = correlation_id or generate_correlation_id()
        self.previous_correlation_id = None
    
    def __enter__(self) -> str:
        """
        Enter context manager and set correlation ID.
        
        Returns:
            The correlation ID for this context
        """
        self.previous_correlation_id = get_correlation_id()
        set_correlation_id(self.correlation_id)
        return self.correlation_id
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit context manager and restore previous correlation ID.
        """
        set_correlation_id(self.previous_correlation_id)


def with_correlation_id(correlation_id: Optional[str] = None):
    """
    Decorator to run function with specific correlation ID.
    
    This decorator ensures that a function runs with a specific
    correlation ID context, useful for background tasks or async operations.
    
    Args:
        correlation_id: Optional correlation ID, generates new one if None
        
    Returns:
        Decorator function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with CorrelationIdManager(correlation_id):
                return func(*args, **kwargs)
        return wrapper
    return decorator


async def correlation_id_middleware(request: Request, call_next):
    """
    FastAPI middleware to handle correlation ID extraction and propagation.
    
    This middleware:
    1. Extracts correlation ID from request headers
    2. Sets it in context for the request duration
    3. Adds it to response headers
    4. Ensures cleanup after request
    
    Args:
        request: FastAPI request object
        call_next: Next middleware/handler in chain
        
    Returns:
        Response with correlation ID headers
    """
    # Extract or generate correlation ID
    correlation_id = extract_correlation_id_from_request(request)
    
    # Set in context for this request
    with CorrelationIdManager(correlation_id):
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        add_correlation_id_to_response(response, correlation_id)
        
        return response


def trace_operation(operation_name: str, **metadata):
    """
    Context manager for tracing operations with correlation ID.
    
    This context manager helps trace operations by automatically
    logging start and end events with correlation ID and metadata.
    
    Args:
        operation_name: Name of the operation being traced
        **metadata: Additional metadata to include in traces
    """
    from .logging import get_logger
    
    class OperationTracer:
        def __init__(self, op_name: str, meta: dict):
            self.operation_name = op_name
            self.metadata = meta
            self.logger = get_logger("tracer")
            self.start_time = None
        
        def __enter__(self):
            import time
            self.start_time = time.time()
            
            self.logger.info(
                "Operation started",
                operation=self.operation_name,
                event="operation_start",
                **self.metadata
            )
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            import time
            duration = time.time() - self.start_time if self.start_time else 0
            
            if exc_type is None:
                self.logger.info(
                    "Operation completed successfully",
                    operation=self.operation_name,
                    event="operation_complete",
                    duration_seconds=duration,
                    **self.metadata
                )
            else:
                self.logger.error(
                    "Operation failed",
                    operation=self.operation_name,
                    event="operation_error",
                    duration_seconds=duration,
                    error=str(exc_val),
                    error_type=exc_type.__name__ if exc_type else None,
                    **self.metadata
                )
    
    return OperationTracer(operation_name, metadata)