"""
Unified execution response schemas for the AI Workflow Engine.

This module contains the standardized response schemas used across
all API endpoints to eliminate duplication and ensure consistency.

Author: AI Workflow Engine Team
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from .base import BaseResponse, BaseDataResponse


class NodeData(BaseModel):
    """
    Standardized node execution data response.
    
    This unified schema replaces multiple duplicate node result formats
    throughout the API layer, providing a single source of truth for
    node execution results.
    """
    
    node_id: str = Field(..., description="Unique identifier of the executed node")
    node_name: str = Field(..., description="Human-readable name of the node")
    node_type: str = Field(..., description="Type of node (agent, tool, mcp_tool, etc.)")
    status: str = Field(..., description="Execution status (success, failed, skipped, etc.)")
    
    # Timing information
    started_at: Optional[str] = Field(None, description="ISO timestamp when node execution started")
    finished_at: Optional[str] = Field(None, description="ISO timestamp when node execution finished")
    duration_seconds: Optional[float] = Field(None, description="Execution duration in seconds")
    
    # Output data
    response: Optional[str] = Field(
        None, 
        description="Simple text response extracted from node output"
    )
    structured_output: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured output data when node has JSON schema configuration"
    )
    
    # Error information
    error: Optional[str] = Field(None, description="Error message if node execution failed")
    
    # Metadata
    attempts: int = Field(1, description="Number of execution attempts (for retry tracking)")
    has_output: bool = Field(False, description="Whether node produced any output")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class ExecutionData(BaseModel):
    """
    Core execution data containing all workflow execution information.
    
    This unified data model serves as the foundation for all execution
    response formats, eliminating the need for multiple conversion functions.
    """
    
    # Identifiers
    run_id: str = Field(..., description="Unique execution run identifier")
    workflow_id: str = Field(..., description="Workflow definition identifier")
    
    # Status information
    status: str = Field(..., description="Overall execution status")
    success: bool = Field(..., description="Whether execution completed successfully")
    
    # Timing information
    started_at: str = Field(..., description="ISO timestamp when execution started")
    finished_at: Optional[str] = Field(None, description="ISO timestamp when execution finished")
    duration_seconds: Optional[float] = Field(None, description="Total execution duration in seconds")
    
    # Results
    nodes: List[NodeData] = Field(
        default_factory=list,
        description="Results from individual node executions"
    )
    output: Dict[str, Any] = Field(
        default_factory=dict,
        description="Final workflow output data"
    )
    
    # Metrics
    success_rate: float = Field(0.0, description="Percentage of nodes that executed successfully")
    total_retries: int = Field(0, description="Total number of retries across all nodes")
    
    # Error information
    error: Optional[str] = Field(None, description="Error message if execution failed")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class ExecutionResponse(BaseDataResponse):
    """
    Standard workflow execution API response.
    
    This is the primary response format for workflow execution endpoints,
    providing a consistent structure across all API versions.
    """
    
    data: ExecutionData = Field(..., description="Execution result data")
    
    @classmethod
    def from_domain(
        cls,
        execution_result: 'ExecutionResult',
        correlation_id: Optional[str] = None
    ) -> 'ExecutionResponse':
        """
        Create execution response from domain ExecutionResult.
        
        This is the **SINGLE IMPLEMENTATION** that replaces all the duplicate
        conversion functions scattered throughout the API layer.
        
        Args:
            execution_result: Domain execution result object
            correlation_id: Optional correlation ID for tracing
            
        Returns:
            Standardized ExecutionResponse
        """
        from ....services.response_service import ResponseService
        
        # Convert node results using centralized service
        node_data_list = ResponseService.convert_node_results_to_api_format(
            execution_result.node_results,
            execution_result.context.input_data if execution_result.context else {}
        )
        
        # Create execution data
        execution_data = ExecutionData(
            run_id=execution_result.run_id,
            workflow_id=execution_result.workflow_id,
            status=execution_result.status.value,
            success=execution_result.is_successful,
            started_at=execution_result.started_at.isoformat(),
            finished_at=execution_result.finished_at.isoformat() if execution_result.finished_at else None,
            duration_seconds=execution_result.duration_seconds,
            nodes=node_data_list,
            output=execution_result.output,
            success_rate=execution_result.success_rate,
            total_retries=execution_result.total_retries,
            error=execution_result.error.message if execution_result.error else None
        )
        
        return cls(
            success=execution_result.is_successful,
            message="Workflow execution completed" if execution_result.is_successful else "Workflow execution failed",
            correlation_id=correlation_id,
            data=execution_data
        )


class SimpleExecutionResponse(BaseResponse):
    """
    Simplified execution response for backward compatibility.
    
    This maintains compatibility with existing API consumers while
    using the same underlying unified conversion logic.
    """
    
    # Legacy fields for backward compatibility
    run_id: str = Field(..., description="Unique execution run identifier")
    workflow_id: str = Field(..., description="Workflow definition identifier")
    status: str = Field(..., description="Overall execution status")
    success: bool = Field(..., description="Whether execution completed successfully")
    started_at: str = Field(..., description="ISO timestamp when execution started")
    finished_at: Optional[str] = Field(None, description="ISO timestamp when execution finished")
    duration_seconds: Optional[float] = Field(None, description="Total execution duration in seconds")
    nodes: List[NodeData] = Field(default_factory=list, description="Node execution results")
    
    @classmethod
    def from_domain(
        cls,
        execution_result: 'ExecutionResult',
        correlation_id: Optional[str] = None
    ) -> 'SimpleExecutionResponse':
        """
        Create simplified response from domain ExecutionResult.
        
        This uses the same centralized conversion logic as the full response
        but maintains the flattened structure for backward compatibility.
        
        Args:
            execution_result: Domain execution result object
            correlation_id: Optional correlation ID for tracing
            
        Returns:
            Simplified ExecutionResponse for backward compatibility
        """
        from ....services.response_service import ResponseService
        
        # Convert node results using centralized service (same logic as full response)
        node_data_list = ResponseService.convert_node_results_to_api_format(
            execution_result.node_results,
            execution_result.context.input_data if execution_result.context else {}
        )
        
        return cls(
            success=execution_result.is_successful,
            message="Workflow execution completed" if execution_result.is_successful else "Workflow execution failed",
            correlation_id=correlation_id,
            run_id=execution_result.run_id,
            workflow_id=execution_result.workflow_id,
            status=execution_result.status.value,
            started_at=execution_result.started_at.isoformat(),
            finished_at=execution_result.finished_at.isoformat() if execution_result.finished_at else None,
            duration_seconds=execution_result.duration_seconds,
            nodes=node_data_list
        )


class ExecutionListData(BaseModel):
    """Data model for execution list responses."""
    
    executions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of execution summaries"
    )
    total_count: int = Field(0, description="Total number of executions")
    offset: int = Field(0, description="Offset used for pagination")
    limit: int = Field(50, description="Limit used for pagination")
    has_more: bool = Field(False, description="Whether there are more results available")


class ExecutionListResponse(BaseDataResponse):
    """Response for listing workflow executions."""
    
    data: ExecutionListData = Field(..., description="Execution list data")
    
    @classmethod
    def from_execution_results(
        cls,
        execution_results: List['ExecutionResult'],
        total_count: int,
        offset: int = 0,
        limit: int = 50,
        correlation_id: Optional[str] = None
    ) -> 'ExecutionListResponse':
        """
        Create execution list response from domain objects.
        
        Args:
            execution_results: List of execution results
            total_count: Total number of executions available
            offset: Pagination offset
            limit: Pagination limit
            correlation_id: Optional correlation ID
            
        Returns:
            ExecutionListResponse with summary data
        """
        executions = []
        for result in execution_results:
            executions.append({
                "run_id": result.run_id,
                "workflow_id": result.workflow_id,
                "status": result.status.value,
                "success": result.is_successful,
                "started_at": result.started_at.isoformat(),
                "finished_at": result.finished_at.isoformat() if result.finished_at else None,
                "duration_seconds": result.duration_seconds,
                "success_rate": result.success_rate,
                "node_count": len(result.node_results),
                "has_error": result.error is not None
            })
        
        list_data = ExecutionListData(
            executions=executions,
            total_count=total_count,
            offset=offset,
            limit=limit,
            has_more=(offset + len(executions)) < total_count
        )
        
        return cls(
            success=True,
            message=f"Found {len(executions)} executions",
            correlation_id=correlation_id,
            data=list_data
        )


class ValidationErrorResponse(BaseResponse):
    """Response for validation errors."""
    
    errors: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of validation errors"
    )
    
    @classmethod
    def from_validation_error(
        cls,
        error: 'ValidationError',
        correlation_id: Optional[str] = None
    ) -> 'ValidationErrorResponse':
        """
        Create validation error response from domain ValidationError.
        
        Args:
            error: Domain validation error
            correlation_id: Optional correlation ID
            
        Returns:
            ValidationErrorResponse with error details
        """
        errors = [{
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "field": error.details.get("field") if hasattr(error, 'details') else None
        }]
        
        return cls(
            success=False,
            message="Validation failed",
            correlation_id=correlation_id,
            errors=errors
        )


class HealthData(BaseModel):
    """Health check data model."""
    
    status: str = Field(..., description="Service health status")
    version: str = Field("1.0.0", description="API version")
    uptime_seconds: Optional[float] = Field(None, description="Service uptime in seconds")
    
    # Service-specific health information
    workflow_service_ready: bool = Field(False, description="Whether workflow service is ready")
    execution_service_ready: bool = Field(False, description="Whether execution service is ready")
    validation_service_ready: bool = Field(False, description="Whether validation service is ready")
    
    # Statistics
    active_executions: int = Field(0, description="Number of currently active executions")
    total_executions: int = Field(0, description="Total executions processed")
    
    # Available capabilities
    available_node_types: List[str] = Field(
        default_factory=list,
        description="List of supported node types"
    )


class HealthResponse(BaseDataResponse):
    """Health check response."""
    
    data: HealthData = Field(..., description="Health check data")
    
    @classmethod
    def create_healthy(
        cls,
        uptime_seconds: Optional[float] = None,
        active_executions: int = 0,
        total_executions: int = 0,
        available_node_types: List[str] = None,
        correlation_id: Optional[str] = None
    ) -> 'HealthResponse':
        """
        Create a healthy status response.
        
        Args:
            uptime_seconds: Service uptime
            active_executions: Number of active executions
            total_executions: Total executions processed
            available_node_types: List of supported node types
            correlation_id: Optional correlation ID
            
        Returns:
            HealthResponse indicating healthy status
        """
        health_data = HealthData(
            status="healthy",
            uptime_seconds=uptime_seconds,
            workflow_service_ready=True,
            execution_service_ready=True,  
            validation_service_ready=True,
            active_executions=active_executions,
            total_executions=total_executions,
            available_node_types=available_node_types or []
        )
        
        return cls(
            success=True,
            message="All services are healthy",
            correlation_id=correlation_id,
            data=health_data
        )
    
    @classmethod
    def create_unhealthy(
        cls,
        error_message: str,
        correlation_id: Optional[str] = None
    ) -> 'HealthResponse':
        """
        Create an unhealthy status response.
        
        Args:
            error_message: Description of health issues
            correlation_id: Optional correlation ID
            
        Returns:
            HealthResponse indicating unhealthy status
        """
        health_data = HealthData(
            status="unhealthy",
            workflow_service_ready=False,
            execution_service_ready=False,
            validation_service_ready=False
        )
        
        return cls(
            success=False,
            message=f"Service health check failed: {error_message}",
            correlation_id=correlation_id,
            data=health_data
        )