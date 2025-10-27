"""
Base exception classes for the AI Workflow Engine.

This module defines the exception hierarchy used throughout the application.
All custom exceptions should inherit from these base classes to ensure
consistent error handling and reporting.

Author: AI Workflow Engine Team
"""

from typing import Any, Dict, Optional


class WorkflowEngineException(Exception):
    """
    Base exception for all workflow engine errors.
    
    This is the root exception class for all custom exceptions in the workflow engine.
    It provides structured error information including error codes, messages, and
    additional context for debugging and error reporting.
    
    Attributes:
        message: Human-readable error message
        code: Machine-readable error code
        details: Additional error context and debugging information
    """
    
    def __init__(
        self, 
        message: str, 
        code: str, 
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the exception.
        
        Args:
            message: Human-readable error message
            code: Machine-readable error code (e.g., "VALIDATION_ERROR")
            details: Additional context and debugging information
        """
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)
    
    def __str__(self) -> str:
        """Return string representation of the exception."""
        return f"{self.code}: {self.message}"
    
    def __repr__(self) -> str:
        """Return detailed string representation of the exception."""
        return (
            f"{self.__class__.__name__}("
            f"message='{self.message}', "
            f"code='{self.code}', "
            f"details={self.details})"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert exception to dictionary format.
        
        Returns:
            Dict containing exception details
        """
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "exception_type": self.__class__.__name__
        }


class ValidationException(WorkflowEngineException):
    """
    Exception raised when validation fails.
    
    This exception is raised when input validation fails, including
    workflow definition validation, input data validation, or schema validation.
    """
    
    def __init__(
        self, 
        message: str, 
        field: Optional[str] = None, 
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize validation exception.
        
        Args:
            message: Human-readable error message
            field: Optional field name that failed validation
            details: Additional validation context
        """
        code = "VALIDATION_ERROR"
        validation_details = details or {}
        
        if field:
            validation_details["field"] = field
            
        super().__init__(message, code, validation_details)


class ExecutionException(WorkflowEngineException):
    """
    Exception raised during workflow execution.
    
    This exception is raised when errors occur during workflow execution,
    including node execution failures, context errors, or runtime issues.
    """
    
    def __init__(
        self, 
        message: str, 
        node_id: Optional[str] = None,
        run_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize execution exception.
        
        Args:
            message: Human-readable error message
            node_id: Optional ID of the node where error occurred
            run_id: Optional workflow run ID
            details: Additional execution context
        """
        code = "EXECUTION_ERROR"
        execution_details = details or {}
        
        if node_id:
            execution_details["node_id"] = node_id
        if run_id:
            execution_details["run_id"] = run_id
            
        super().__init__(message, code, execution_details)


class ConfigurationException(WorkflowEngineException):
    """
    Exception raised when configuration is invalid.
    
    This exception is raised when application configuration is invalid,
    including missing environment variables, invalid settings, or
    service configuration errors.
    """
    
    def __init__(
        self, 
        message: str, 
        config_key: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize configuration exception.
        
        Args:
            message: Human-readable error message
            config_key: Optional configuration key that is invalid
            details: Additional configuration context
        """
        code = "CONFIGURATION_ERROR"
        config_details = details or {}
        
        if config_key:
            config_details["config_key"] = config_key
            
        super().__init__(message, code, config_details)


class ExternalServiceException(WorkflowEngineException):
    """
    Exception raised when external service calls fail.
    
    This exception is raised when calls to external services fail,
    including AI providers, MCP servers, or database connections.
    """
    
    def __init__(
        self, 
        message: str, 
        service_name: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize external service exception.
        
        Args:
            message: Human-readable error message
            service_name: Optional name of the external service
            status_code: Optional HTTP status code if applicable
            details: Additional service context
        """
        code = "EXTERNAL_SERVICE_ERROR"
        service_details = details or {}
        
        if service_name:
            service_details["service_name"] = service_name
        if status_code:
            service_details["status_code"] = status_code
            
        super().__init__(message, code, service_details)


class BusinessLogicException(WorkflowEngineException):
    """
    Exception raised when business logic constraints are violated.
    
    This exception is raised when business rules are violated,
    including workflow constraints, node dependencies, or domain rules.
    """
    
    def __init__(
        self, 
        message: str, 
        rule: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize business logic exception.
        
        Args:
            message: Human-readable error message
            rule: Optional business rule that was violated
            details: Additional business context
        """
        code = "BUSINESS_LOGIC_ERROR"
        business_details = details or {}
        
        if rule:
            business_details["violated_rule"] = rule
            
        super().__init__(message, code, business_details)


class ResourceNotFoundException(WorkflowEngineException):
    """
    Exception raised when a requested resource is not found.
    
    This exception is raised when trying to access resources that don't exist,
    including workflow executions, node definitions, or configuration items.
    """
    
    def __init__(
        self, 
        message: str, 
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize resource not found exception.
        
        Args:
            message: Human-readable error message
            resource_type: Optional type of resource (e.g., "workflow", "execution")
            resource_id: Optional ID of the missing resource
            details: Additional resource context
        """
        code = "RESOURCE_NOT_FOUND"
        resource_details = details or {}
        
        if resource_type:
            resource_details["resource_type"] = resource_type
        if resource_id:
            resource_details["resource_id"] = resource_id
            
        super().__init__(message, code, resource_details)


class PermissionDeniedException(WorkflowEngineException):
    """
    Exception raised when access is denied.
    
    This exception is raised when a user or service doesn't have
    permission to perform a requested operation.
    """
    
    def __init__(
        self, 
        message: str, 
        operation: Optional[str] = None,
        resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize permission denied exception.
        
        Args:
            message: Human-readable error message
            operation: Optional operation that was denied
            resource: Optional resource that access was denied to
            details: Additional permission context
        """
        code = "PERMISSION_DENIED"
        permission_details = details or {}
        
        if operation:
            permission_details["operation"] = operation
        if resource:
            permission_details["resource"] = resource
            
        super().__init__(message, code, permission_details)


# Convenience aliases for common exceptions
ValidationError = ValidationException
ExecutionError = ExecutionException
ConfigurationError = ConfigurationException