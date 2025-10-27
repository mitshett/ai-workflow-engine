"""
Structured logging utilities for the AI Workflow Engine.

This module provides structured logging capabilities with correlation ID support,
ensuring consistent log formatting and traceability across the entire application.

Author: AI Workflow Engine Team
"""

import logging
import sys
from typing import Any, Dict, Optional
from contextvars import ContextVar

import structlog
from structlog.types import FilteringBoundLogger


# Context variable for correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


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


def add_correlation_id(logger: FilteringBoundLogger, name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add correlation ID to log event if available.
    
    This processor automatically adds the correlation ID from context
    to all log events for request tracing.
    
    Args:
        logger: The logger instance
        name: The logger name
        event_dict: The event dictionary
        
    Returns:
        Updated event dictionary with correlation ID
    """
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def configure_logging(
    level: str = "INFO",
    json_format: bool = True,
    include_timestamp: bool = True
) -> None:
    """
    Configure simplified logging for the application.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: Whether to output logs in JSON format (ignored for now)
        include_timestamp: Whether to include timestamps in logs
    """
    # Configure standard library logging with simple format
    log_format = "%(asctime)s [%(levelname)8s] %(message)s" if include_timestamp else "%(levelname)s: %(message)s"
    logging.basicConfig(
        format=log_format,
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
        force=True
    )


class SafeLoggerAdapter:
    """Logger adapter that safely handles keyword arguments."""
    
    def __init__(self, logger):
        self.logger = logger
    
    def _format_message(self, msg, **kwargs):
        # Filter out standard logging kwargs that should be handled separately
        standard_kwargs = {'exc_info', 'stack_info', 'stacklevel', 'extra'}
        filtered_kwargs = {k: v for k, v in kwargs.items() if k not in standard_kwargs}
        
        if filtered_kwargs:
            # Convert keyword arguments to string format
            extra_info = " - " + ", ".join([f"{k}: {v}" for k, v in filtered_kwargs.items()])
            formatted_msg = f"{msg}{extra_info}"
        else:
            formatted_msg = msg
            
        # Return message and any standard kwargs
        standard_args = {k: v for k, v in kwargs.items() if k in standard_kwargs}
        return formatted_msg, standard_args
    
    def debug(self, msg, **kwargs):
        formatted_msg, standard_args = self._format_message(msg, **kwargs)
        self.logger.debug(formatted_msg, **standard_args)
    
    def info(self, msg, **kwargs):
        formatted_msg, standard_args = self._format_message(msg, **kwargs)
        self.logger.info(formatted_msg, **standard_args)
    
    def warning(self, msg, **kwargs):
        formatted_msg, standard_args = self._format_message(msg, **kwargs)
        self.logger.warning(formatted_msg, **standard_args)
    
    def error(self, msg, **kwargs):
        formatted_msg, standard_args = self._format_message(msg, **kwargs)
        self.logger.error(formatted_msg, **standard_args)
    
    def critical(self, msg, **kwargs):
        formatted_msg, standard_args = self._format_message(msg, **kwargs)
        self.logger.critical(formatted_msg, **standard_args)
    
    def bind(self, **kwargs):
        """Return self for compatibility with structlog bind() calls."""
        # For now, just return self - we could enhance this later
        return self


def get_logger(name: str):
    """
    Get a safe logger instance that handles keyword arguments.
    
    Args:
        name: The logger name (typically __name__)
        
    Returns:
        Safe logger adapter
    """
    return SafeLoggerAdapter(logging.getLogger(name))


class LoggerMixin:
    """
    Mixin class that provides logger instance to other classes.
    
    This mixin automatically creates a logger instance based on
    the class name, making it easy to add logging to any class.
    """
    
    @property
    def logger(self):
        """Get logger instance for this class."""
        if not hasattr(self, '_logger'):
            self._logger = get_logger(self.__class__.__module__ + '.' + self.__class__.__name__)
        return self._logger


def log_function_call(
    include_args: bool = True,
    include_result: bool = False,
    level: str = "DEBUG"
) -> Any:
    """
    Decorator to automatically log function calls.
    
    This decorator logs function entry and exit, optionally including
    arguments and return values for debugging purposes.
    
    Args:
        include_args: Whether to include function arguments in logs
        include_result: Whether to include return value in logs
        level: Log level for the messages
        
    Returns:
        Decorator function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            func_name = func.__name__
            
            # Log function entry
            log_data = {"function": func_name}
            if include_args:
                log_data["args"] = args
                log_data["kwargs"] = kwargs
            
            getattr(logger, level.lower())("Function call started", **log_data)
            
            try:
                # Execute function
                result = func(*args, **kwargs)
                
                # Log successful completion
                log_data = {"function": func_name}
                if include_result:
                    log_data["result"] = result
                
                getattr(logger, level.lower())("Function call completed", **log_data)
                
                return result
                
            except Exception as e:
                # Log exception
                logger.error(
                    "Function call failed",
                    function=func_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
                raise
        
        return wrapper
    return decorator


def log_execution_time():
    """
    Decorator to log function execution time.
    
    This decorator measures and logs the execution time of functions,
    useful for performance monitoring and optimization.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            import time
            
            logger = get_logger(func.__module__)
            func_name = func.__name__
            
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                logger.info(
                    "Function execution completed",
                    function=func_name,
                    execution_time_seconds=execution_time
                )
                
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                
                logger.error(
                    "Function execution failed",
                    function=func_name,
                    execution_time_seconds=execution_time,
                    error=str(e),
                    error_type=type(e).__name__
                )
                raise
        
        return wrapper
    return decorator


# Pre-configured logger instances for common use cases
audit_logger = get_logger("audit")
security_logger = get_logger("security")
performance_logger = get_logger("performance")
business_logger = get_logger("business")