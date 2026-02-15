"""
Clean Workflow Execution API (v1) with Dependency Injection.

This module implements the clean architecture pattern with:
- Proper separation of concerns
- Dependency injection
- Centralized response transformation (ELIMINATES CODE DUPLICATION)
- Standardized error handling
- Domain-driven design

Author: AI Workflow Engine Team
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import uuid4

# Import clean architecture components
from ...app.dependencies import (
    get_workflow_service,
    get_response_service,
    get_correlation_id_dependency,
    get_request_logger,
)
from ...services import WorkflowService
from ...shared.schemas.responses import (
    ExecutionResponse,
    SimpleExecutionResponse,
    ExecutionListResponse,
    HealthResponse,
    ValidationErrorResponse,
)
from ...domain.exceptions.base import (
    ValidationError,
    ExecutionError,
    BusinessLogicException,
    ResourceNotFoundException,
)

# Set up router
router = APIRouter(
    prefix="/api/v1/workflows",
    tags=["workflow-execution"],
    responses={
        400: {"description": "Invalid workflow definition or input"},
        404: {"description": "Workflow execution not found"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)


# Request/Response Models

class WorkflowExecutionRequest(BaseModel):
    """Request model for workflow execution."""
    
    definition: Dict[str, Any] = Field(
        ...,
        description="Complete workflow definition to execute",
        example={
            "id": "simple_weather_workflow",
            "name": "Weather Information Workflow",
            "nodes": [
                {
                    "id": "workflow_start",
                    "type": "start",
                    "config": {"name": "Start"},
                    "next": ["weather_agent"]
                },
                {
                    "id": "weather_agent",
                    "type": "agent",
                    "config": {
                        "provider": "azure_openai",
                        "model": "gpt-4o-mini",
                        "prompt": "Provide weather info for Bengaluru, India"
                    },
                    "next": ["workflow_end"]
                },
                {
                    "id": "workflow_end",
                    "type": "end",
                    "config": {"name": "End", "collect_outputs": True},
                    "next": []
                }
            ]
        }
    )
    input_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for workflow execution",
        example={
            "request_id": "weather_001",
            "location": "Bengaluru, India",
            "requester": "API User"
        }
    )
    run_id: Optional[str] = Field(
        None,
        description="Optional custom run ID (UUID will be generated if not provided)"
    )
    execution_options: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional execution configuration",
        example={
            "max_parallel_nodes": 5,
            "continue_on_failure": False,
            "timeout_seconds": 600
        }
    )


class WorkflowDefinitionRequest(BaseModel):
    """Request model for workflow definition operations."""
    
    name: str = Field(..., description="Human-readable workflow name")
    definition: Dict[str, Any] = Field(..., description="Workflow definition dictionary")
    description: Optional[str] = Field(None, description="Optional workflow description")


# API Endpoints

@router.post(
    "/execute",
    response_model=SimpleExecutionResponse,
    summary="Execute Workflow",
    description="Execute a complete workflow definition with clean architecture and centralized response handling",
    response_description="Standardized execution results with no code duplication"
)
async def execute_workflow(
    request: WorkflowExecutionRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    correlation_id: str = Depends(get_correlation_id_dependency),
    logger = Depends(get_request_logger)
) -> SimpleExecutionResponse:
    """
    Execute a complete workflow definition using clean architecture.
    
    This endpoint demonstrates the new clean architecture with:
    - Proper dependency injection
    - Domain service orchestration
    - Centralized response transformation (NO CODE DUPLICATION)
    - Standardized error handling
    
    Args:
        request: Workflow execution request with definition and input data
        workflow_service: Injected WorkflowService (clean architecture)
        correlation_id: Request correlation ID for tracing
        logger: Request-scoped logger with correlation context
        
    Returns:
        SimpleExecutionResponse: Standardized execution results
        
    Raises:
        HTTPException: With appropriate status codes and error details
    """
    run_id = request.run_id or str(uuid4())
    
    logger.info(f"Starting workflow execution via clean API - workflow_name: {request.definition.get('name', 'unknown')}, run_id: {run_id}, correlation_id: {correlation_id}")
    
    try:
        # Execute workflow using domain service - CLEAN ARCHITECTURE
        execution_result = await workflow_service.execute_workflow_from_definition(
            definition=request.definition,
            input_data=request.input_data,
            run_id=run_id,
            execution_options=request.execution_options
        )
        
        # Convert to API response using CENTRALIZED service - NO DUPLICATION
        api_response = SimpleExecutionResponse.from_domain(
            execution_result=execution_result,
            correlation_id=correlation_id
        )
        
        logger.info(f"Workflow execution completed successfully - run_id: {run_id}, status: {execution_result.status.value}, duration_seconds: {execution_result.duration_seconds}, success_rate: {execution_result.success_rate}")
        
        return api_response
        
    except ValidationError as e:
        logger.warning(f"Workflow validation failed - run_id: {run_id}, error: {e.message}, details: {e.details}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow validation failed: {e.message}"
        )
        
    except ExecutionError as e:
        logger.error(f"Workflow execution failed - run_id: {run_id}, error: {e.message}, details: {e.details}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed: {e.message}"
        )
        
    except Exception as e:
        logger.error(
            f"Unexpected error during workflow execution - run_id: {run_id}, error: {str(e)}, error_type: {e.__class__.__name__}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post(
    "/execute/full",
    response_model=ExecutionResponse,
    summary="Execute Workflow (Full Response)",
    description="Execute workflow with comprehensive execution details and metrics"
)
async def execute_workflow_full(
    request: WorkflowExecutionRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    correlation_id: str = Depends(get_correlation_id_dependency),
    logger = Depends(get_request_logger)
) -> ExecutionResponse:
    """
    Execute workflow with full detailed response format.
    
    This endpoint returns the comprehensive ExecutionResponse with detailed
    metrics, timing information, and structured data.
    
    Args:
        request: Workflow execution request
        workflow_service: Injected WorkflowService
        correlation_id: Request correlation ID
        logger: Request-scoped logger
        
    Returns:
        ExecutionResponse: Comprehensive execution results with full details
    """
    run_id = request.run_id or str(uuid4())
    
    logger.info(
        "Starting workflow execution (full response)",
        workflow_name=request.definition.get('name', 'unknown'),
        run_id=run_id
    )
    
    try:
        # Execute workflow using domain service
        execution_result = await workflow_service.execute_workflow_from_definition(
            definition=request.definition,
            input_data=request.input_data,
            run_id=run_id,
            execution_options=request.execution_options
        )
        
        # Convert to full API response using CENTRALIZED service
        api_response = ExecutionResponse.from_domain(
            execution_result=execution_result,
            correlation_id=correlation_id
        )
        
        logger.info(
            "Workflow execution completed (full response)",
            run_id=run_id,
            status=execution_result.status.value,
            node_count=len(execution_result.node_results)
        )
        
        return api_response
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Workflow validation failed: {e.message}"
        )
        
    except Exception as e:
        logger.error(
            "Workflow execution failed (full response)",
            run_id=run_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution failed: {str(e)}"
        )


@router.get(
    "/executions/{run_id}",
    response_model=ExecutionResponse,
    summary="Get Execution Result",
    description="Retrieve detailed results of a specific workflow execution"
)
async def get_execution_result(
    run_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    correlation_id: str = Depends(get_correlation_id_dependency),
    logger = Depends(get_request_logger)
) -> ExecutionResponse:
    """
    Get execution results for a specific run ID.
    
    Args:
        run_id: The execution run ID to retrieve
        workflow_service: Injected WorkflowService
        correlation_id: Request correlation ID
        logger: Request-scoped logger
        
    Returns:
        ExecutionResponse: Complete execution results
        
    Raises:
        HTTPException: 404 if execution not found
    """
    logger.info(f"Retrieving execution result - run_id: {run_id}")
    
    try:
        # Get execution result using domain service
        execution_result = await workflow_service.get_execution_result(run_id)
        
        if not execution_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Execution with run_id '{run_id}' not found"
            )
        
        # Convert to API response using CENTRALIZED service
        api_response = ExecutionResponse.from_domain(
            execution_result=execution_result,
            correlation_id=correlation_id
        )
        
        return api_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to retrieve execution result",
            run_id=run_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve execution: {str(e)}"
        )


@router.get(
    "/executions",
    response_model=ExecutionListResponse,
    summary="List Workflow Executions",
    description="Get a paginated list of workflow executions with filtering options"
)
async def list_executions(
    limit: int = 50,
    offset: int = 0,
    workflow_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    correlation_id: str = Depends(get_correlation_id_dependency),
    logger = Depends(get_request_logger)
) -> ExecutionListResponse:
    """
    List workflow executions with pagination and filtering.
    
    Args:
        limit: Maximum number of results to return (default: 50)
        offset: Number of results to skip for pagination (default: 0)
        workflow_id: Optional filter by workflow ID
        status_filter: Optional filter by execution status
        workflow_service: Injected WorkflowService
        correlation_id: Request correlation ID
        logger: Request-scoped logger
        
    Returns:
        ExecutionListResponse: Paginated list of execution summaries
    """
    logger.info(
        "Listing workflow executions",
        limit=limit,
        offset=offset,
        workflow_id=workflow_id,
        status_filter=status_filter
    )
    
    try:
        # Parse status filter
        from ...domain.enums.execution_status import ExecutionStatus
        status_enum = None
        if status_filter:
            try:
                status_enum = ExecutionStatus(status_filter)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status filter: {status_filter}"
                )
        
        # Get executions using domain service
        if workflow_id:
            execution_results = await workflow_service.list_workflow_executions(
                workflow_id=workflow_id,
                limit=limit,
                offset=offset,
                status_filter=status_enum
            )
            total_count = len(execution_results)  # Simplified for now
        else:
            # TODO: Implement global execution listing when repository is ready
            execution_results = []
            total_count = 0
        
        # Convert to API response using CENTRALIZED service
        api_response = ExecutionListResponse.from_execution_results(
            execution_results=execution_results,
            total_count=total_count,
            offset=offset,
            limit=limit,
            correlation_id=correlation_id
        )
        
        logger.info(
            "Listed workflow executions",
            result_count=len(execution_results),
            total_count=total_count
        )
        
        return api_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to list executions",
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list executions: {str(e)}"
        )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Execution Service Health Check",
    description="Check the health and status of the workflow execution service"
)
async def get_execution_health(
    correlation_id: str = Depends(get_correlation_id_dependency),
    logger = Depends(get_request_logger)
) -> HealthResponse:
    """
    Get health status of the execution service.
    
    Returns comprehensive health information including:
    - Service readiness status
    - Available capabilities
    - Performance metrics
    - System status
    
    Args:
        correlation_id: Request correlation ID
        logger: Request-scoped logger
        
    Returns:
        HealthResponse: Current service health information
    """
    logger.debug("Checking execution service health")
    
    try:
        # TODO: Add actual health checks when infrastructure is ready
        available_node_types = [
            "start", "end", "agent", "tool", "mcp_tool", "condition"
        ]
        
        # Create healthy response using CENTRALIZED schema
        api_response = HealthResponse.create_healthy(
            uptime_seconds=None,  # TODO: Track actual uptime
            active_executions=0,  # TODO: Track active executions
            total_executions=0,   # TODO: Track total executions
            available_node_types=available_node_types,
            correlation_id=correlation_id
        )
        
        logger.info("Health check completed successfully")
        return api_response
        
    except Exception as e:
        logger.error(
            "Health check failed",
            error=str(e)
        )
        
        # Create unhealthy response using CENTRALIZED schema
        return HealthResponse.create_unhealthy(
            error_message=str(e),
            correlation_id=correlation_id
        )


@router.post(
    "/validate",
    response_model=SimpleExecutionResponse,
    summary="Validate Workflow Definition",
    description="Validate a workflow definition without executing it"
)
async def validate_workflow(
    request: WorkflowDefinitionRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service),
    correlation_id: str = Depends(get_correlation_id_dependency),
    logger = Depends(get_request_logger)
) -> Dict[str, Any]:
    """
    Validate a workflow definition without executing it.
    
    This endpoint performs comprehensive validation including:
    - Syntax validation
    - Schema validation  
    - Business rule validation
    - DAG structure validation
    
    Args:
        request: Workflow definition to validate
        workflow_service: Injected WorkflowService
        correlation_id: Request correlation ID
        logger: Request-scoped logger
        
    Returns:
        Validation results with detailed feedback
    """
    logger.info(
        "Validating workflow definition",
        workflow_name=request.name
    )
    
    try:
        # Create workflow using domain service (this validates it)
        workflow = await workflow_service.create_workflow(
            name=request.name,
            definition=request.definition,
            description=request.description
        )
        
        logger.info(
            "Workflow validation successful",
            workflow_id=workflow.id,
            node_count=workflow.node_count
        )
        
        return {
            "success": True,
            "message": "Workflow definition is valid",
            "correlation_id": correlation_id,
            "validation_results": {
                "workflow_id": workflow.id,
                "name": workflow.name,
                "node_count": workflow.node_count,
                "connection_count": workflow.connection_count,
                "is_valid": workflow.is_valid
            }
        }
        
    except ValidationError as e:
        logger.warning(
            "Workflow validation failed",
            workflow_name=request.name,
            error=e.message
        )
        
        # Return detailed validation error using CENTRALIZED schema
        validation_response = ValidationErrorResponse.from_validation_error(
            error=e,
            correlation_id=correlation_id
        )
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation_response.model_dump()
        )
        
    except Exception as e:
        logger.error(
            "Unexpected error during validation",
            workflow_name=request.name,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: {str(e)}"
        )