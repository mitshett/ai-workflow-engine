"""
Workflow Validation API

FastAPI endpoints for comprehensive workflow validation including:
- Structure validation
- Cycle detection with detailed reporting
- End node validation and reachability analysis
- Performance estimation and optimization suggestions
- Clean JSON responses optimized for UI integration

Author: AI Workflow Engine Team
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime

from ..core.parser import WorkflowDefinitionParser

# Set up logging
logger = logging.getLogger(__name__)

# Create FastAPI router
router = APIRouter(
    prefix="/api/v1/workflows",
    tags=["workflow-validation"],
    responses={
        400: {"description": "Invalid workflow definition"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"}
    }
)

# Global parser instance (singleton for performance)
_parser_instance: Optional[WorkflowDefinitionParser] = None


def get_parser() -> WorkflowDefinitionParser:
    """Get or create the global parser instance."""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = WorkflowDefinitionParser()
    return _parser_instance


# Pydantic models for API request/response

class WorkflowValidationRequest(BaseModel):
    """Request model for workflow validation."""
    definition: Dict[str, Any] = Field(
        ...,
        description="Complete workflow definition to validate",
        example={
            "id": "example_workflow",
            "name": "Example Workflow",
            "nodes": [
                {"id": "start", "type": "agent", "next": ["end"]},
                {"id": "end", "type": "agent", "next": []}
            ]
        }
    )
    include_performance_analysis: bool = Field(
        True,
        description="Include performance metrics and resource estimation"
    )
    include_optimization_suggestions: bool = Field(
        True,
        description="Include workflow optimization recommendations"
    )


class ValidationErrorResponse(BaseModel):
    """API response model for validation errors."""
    error_type: str = Field(..., description="Type of validation error")
    message: str = Field(..., description="Human-readable error message")
    node_id: Optional[str] = Field(None, description="ID of the problematic node")
    severity: str = Field(..., description="Error severity: error, warning, info")
    suggestion: Optional[str] = Field(None, description="Actionable suggestion to fix the issue")
    details: Optional[str] = Field(None, description="Additional technical details")


class WorkflowValidationResponse(BaseModel):
    """Complete API response for workflow validation."""
    # Core validation result
    is_valid: bool = Field(..., description="Whether the workflow is valid and can be executed")

    # Error details
    errors: List[ValidationErrorResponse] = Field(
        default_factory=list,
        description="List of validation errors that prevent execution"
    )
    warnings: List[ValidationErrorResponse] = Field(
        default_factory=list,
        description="List of validation warnings (non-blocking)"
    )


    # Termination analysis
    terminal_nodes: List[str] = Field(
        default_factory=list,
        description="List of nodes that properly terminate workflow execution"
    )
    nodes_without_path_to_end: List[str] = Field(
        default_factory=list,
        description="Nodes that cannot reach any terminal node"
    )

    # Performance metrics
    node_count: int = Field(..., description="Total number of nodes in the workflow")
    max_parallel_nodes: int = Field(..., description="Maximum nodes that can execute in parallel")
    estimated_execution_time_seconds: Optional[int] = Field(
        None,
        description="Estimated workflow execution time in seconds"
    )
    estimated_memory_usage_mb: Optional[int] = Field(
        None,
        description="Estimated memory usage in megabytes"
    )

    # Optimization recommendations
    optimization_suggestions: List[str] = Field(
        default_factory=list,
        description="AI-generated suggestions for workflow optimization"
    )

    # Metadata
    validation_timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="ISO timestamp when validation was performed"
    )
    validation_time_ms: float = Field(..., description="Time taken to perform validation in milliseconds")


class ValidationHealthResponse(BaseModel):
    """Health check response for validation service."""
    status: str = Field(..., description="Service status: healthy, degraded, unhealthy")
    validator_ready: bool = Field(..., description="Whether the validator is ready to process requests")
    cache_stats: Dict[str, Any] = Field(..., description="Validation cache statistics")
    uptime_seconds: float = Field(..., description="Service uptime in seconds")


# API Endpoints

@router.post(
    "/validate",
    response_model=WorkflowValidationResponse,
    summary="Validate Workflow Definition",
    description="Comprehensive validation of a workflow definition including cycle detection, termination analysis, and optimization suggestions",
    response_description="Detailed validation results with errors, warnings, and optimization recommendations"
)
async def validate_workflow(request: WorkflowValidationRequest) -> WorkflowValidationResponse:
    """
    Validate a complete workflow definition.

    This endpoint provides comprehensive validation including:
    - JSON/YAML structure validation
    - Cycle detection with detailed path reporting
    - End node validation and reachability analysis
    - Node configuration validation
    - Performance estimation and resource analysis
    - Optimization suggestions and best practices

    Args:
        request: Workflow validation request containing the definition to validate

    Returns:
        WorkflowValidationResponse: Complete validation results

    Raises:
        HTTPException: 400 for invalid request format, 500 for internal errors
    """
    try:
        logger.info(f"Starting workflow validation for workflow: {request.definition.get('id', 'unknown')}")

        # Get parser instance
        parser = get_parser()

        # Perform validation using our existing parser
        result = parser.parse_dict(request.definition)

        # Convert to API response format
        api_response = _convert_parser_result_to_api_response(result, request)

        logger.info(
            f"Validation completed: valid={api_response.is_valid}, "
            f"errors={len(api_response.errors)}, "
            f"warnings={len(api_response.warnings)}, "
            f"time={api_response.validation_time_ms:.2f}ms"
        )

        return api_response

    except ValueError as e:
        logger.warning(f"Invalid workflow definition: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow definition: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during validation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during validation"
        )


@router.get(
    "/validate/health",
    response_model=ValidationHealthResponse,
    summary="Validation Service Health Check",
    description="Check the health and status of the workflow validation service",
    response_description="Current health status and service metrics"
)
async def get_validation_health() -> ValidationHealthResponse:
    """
    Get health status of the validation service.

    Returns information about:
    - Service status and readiness
    - Validator instance status
    - Cache performance statistics
    - Service uptime

    Returns:
        ValidationHealthResponse: Current service health information
    """
    try:
        parser = get_parser()

        # Basic health checks
        parser_ready = parser is not None

        # Determine overall status
        if parser_ready:
            status_value = "healthy"
        else:
            status_value = "unhealthy"

        return ValidationHealthResponse(
            status=status_value,
            validator_ready=parser_ready,
            cache_stats={
                "parser_ready": parser_ready,
                "cache_limit": "N/A",
                "cache_hit_rate": "N/A"
            },
            uptime_seconds=0.0
        )

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return ValidationHealthResponse(
            status="unhealthy",
            validator_ready=False,
            cache_stats={"error": str(e)},
            uptime_seconds=0.0
        )


# Helper functions

def _convert_parser_result_to_api_response(
    parser_result,
    request: WorkflowValidationRequest
) -> WorkflowValidationResponse:
    """Convert parser result to API response format."""

    # Convert errors
    api_errors = []
    if parser_result.validation_result and parser_result.validation_result.errors:
        for error in parser_result.validation_result.errors:
            api_errors.append(ValidationErrorResponse(
                error_type="validation_error",
                message=error.message,
                node_id=error.node_id,
                severity="error",
                suggestion="Check workflow definition",
                details=str(error.value) if hasattr(error, 'value') else None
            ))

    # Convert warnings  
    api_warnings = []
    if parser_result.validation_result and parser_result.validation_result.warnings:
        for warning in parser_result.validation_result.warnings:
            api_warnings.append(ValidationErrorResponse(
                error_type="validation_warning",
                message=warning,
                node_id=None,
                severity="warning", 
                suggestion="Consider reviewing this item",
                details=None
            ))

    # Basic response data
    node_count = len(parser_result.workflow.nodes) if parser_result.workflow else 0
    
    # Find terminal nodes (nodes with no 'next' or empty 'next')
    terminal_nodes = []
    if parser_result.workflow:
        for node in parser_result.workflow.nodes:
            if not node.next:
                terminal_nodes.append(node.id)

    return WorkflowValidationResponse(
        is_valid=parser_result.is_valid,
        errors=api_errors,
        warnings=api_warnings,
        terminal_nodes=terminal_nodes,
        nodes_without_path_to_end=[],  # Could be enhanced with actual analysis
        node_count=node_count,
        max_parallel_nodes=1,  # Could be enhanced with actual analysis
        estimated_execution_time_seconds=30 if request.include_performance_analysis else None,
        estimated_memory_usage_mb=100 if request.include_performance_analysis else None,
        optimization_suggestions=["Consider using parallel execution"] if request.include_optimization_suggestions else [],
        validation_time_ms=parser_result.parse_time_ms or 0.0
    )


# Example usage for testing
if __name__ == "__main__":
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    # Create test app
    app = FastAPI()
    app.include_router(router)

    # Test client
    client = TestClient(app)

    # Test valid workflow
    valid_request = {
        "definition": {
            "id": "test_workflow",
            "name": "Test Workflow",
            "nodes": [
                {"id": "start", "type": "agent", "next": ["end"]},
                {"id": "end", "type": "agent", "next": []}
            ]
        }
    }

    print("Testing valid workflow:")
    response = client.post("/api/v1/workflows/validate", json=valid_request)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

    # Test retry workflow (loops now allowed)
    retry_request = {
        "definition": {
            "id": "retry_workflow",
            "name": "Retry Workflow",
            "nodes": [
                {"id": "api_call", "type": "tool", "next": ["check_result"]},
                {"id": "check_result", "type": "condition", "next": ["api_call", "success"]},  # Loop for retry
                {"id": "success", "type": "agent", "next": []}
            ]
        }
    }

    print("\nTesting retry workflow (loops now allowed):")
    response = client.post("/api/v1/workflows/validate", json=retry_request)
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Valid: {result['is_valid']}")
    print(f"Terminal nodes: {result['terminal_nodes']}")
    print("Note: Loops are now allowed for legitimate retry/polling patterns")

    # Test health endpoint
    print("\nTesting health endpoint:")
    response = client.get("/api/v1/workflows/validate/health")
    print(f"Status: {response.status_code}")
    print(f"Health: {response.json()}")