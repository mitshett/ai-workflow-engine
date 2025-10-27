"""
Workflow Execution API

FastAPI endpoints for workflow execution including:
- Workflow execution with real-time progress
- Execution status monitoring
- Result retrieval with detailed output
- Support for both JSON and YAML workflows

Author: AI Workflow Engine Team
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging
import uuid
from datetime import datetime

from ..core.simple_runner import SimpleWorkflowRunner, WorkflowExecutionResult
from ..core.schemas import SimpleNodeResult, SimpleWorkflowExecutionResponse

# Set up logging
logger = logging.getLogger(__name__)

# Create FastAPI router
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

# Global workflow runner instance
_runner_instance: Optional[SimpleWorkflowRunner] = None
# In-memory storage for execution results (in production, use Redis/Database)
_execution_results: Dict[str, WorkflowExecutionResult] = {}


def get_runner() -> SimpleWorkflowRunner:
    """Get or create the global workflow runner instance."""
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = SimpleWorkflowRunner()
    return _runner_instance


# Pydantic models for API request/response

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
                        "model": "gpt-35-turbo",
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


class NodeExecutionResult(BaseModel):
    """Result of individual node execution - standardized format."""
    node_id: str = Field(..., description="ID of the executed node")
    node_name: str = Field(..., description="Human-readable name of the node")
    node_type: str = Field(..., description="Type of the node")
    alias: str = Field(..., description="Node alias for workflow variables")
    status: str = Field(..., description="Execution status (completed, failed, etc.)")
    started_at: Optional[str] = Field(None, description="ISO timestamp when node started")
    finished_at: Optional[str] = Field(None, description="ISO timestamp when node finished")
    duration_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")
    output: Optional[Dict[str, Any]] = Field(None, description="Node output data")
    error: Optional[str] = Field(None, description="Error message if failed")


class WorkflowExecutionResponse(BaseModel):
    """Response model for workflow execution."""
    run_id: str = Field(..., description="Unique execution run ID")
    workflow_id: str = Field(..., description="Workflow definition ID")
    status: str = Field(..., description="Overall execution status")
    success: bool = Field(..., description="Whether execution was successful")
    
    # Timing information
    started_at: str = Field(..., description="ISO timestamp when execution started")
    finished_at: Optional[str] = Field(None, description="ISO timestamp when execution finished")
    duration_seconds: Optional[float] = Field(None, description="Total execution time in seconds")
    
    # Results
    output: Dict[str, Any] = Field(default_factory=dict, description="Final workflow output")
    node_results: Dict[str, NodeExecutionResult] = Field(
        default_factory=dict,
        description="Results from individual node executions"
    )
    
    # Error information
    error: Optional[str] = Field(None, description="Error message if execution failed")
    
    # Metadata
    execution_timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="API response timestamp"
    )


class WorkflowListResponse(BaseModel):
    """Response model for listing workflow executions."""
    executions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of workflow executions"
    )
    total_count: int = Field(..., description="Total number of executions")


class ExecutionHealthResponse(BaseModel):
    """Health check response for execution service."""
    status: str = Field(..., description="Service status")
    runner_ready: bool = Field(..., description="Whether the runner is ready")
    active_executions: int = Field(..., description="Number of active executions")
    total_executions: int = Field(..., description="Total executions processed")
    available_executors: List[str] = Field(
        default_factory=list,
        description="List of available node executors"
    )


# API Endpoints

@router.post(
    "/execute",
    response_model=SimpleWorkflowExecutionResponse,
    summary="Execute Workflow",
    description="Execute a complete workflow definition with the provided input data",
    response_description="Simplified execution results in standard API format"
)
async def execute_workflow(request: WorkflowExecutionRequest) -> SimpleWorkflowExecutionResponse:
    """
    Execute a complete workflow definition.

    This endpoint executes a workflow and returns the complete results including:
    - Overall execution status and timing
    - Individual node execution results
    - Final workflow output
    - Detailed error information if execution fails

    Args:
        request: Workflow execution request with definition and input data

    Returns:
        WorkflowExecutionResponse: Complete execution results

    Raises:
        HTTPException: 400 for invalid workflow, 500 for execution errors
    """
    try:
        logger.info(f"Starting workflow execution: {request.definition.get('id', 'unknown')}")

        # Get runner instance
        runner = get_runner()

        # Generate run ID if not provided
        run_id = request.run_id or str(uuid.uuid4())

        # Execute the workflow
        result: WorkflowExecutionResult = await runner.run_workflow(
            workflow_definition=request.definition,
            input_data=request.input_data,
            run_id=run_id
        )

        # Store result for later retrieval
        _execution_results[run_id] = result

        # Convert to simplified API response format
        api_response = _convert_to_simple_execution_response(result)

        logger.info(
            f"Workflow execution completed: run_id={run_id}, "
            f"status={result.status}, duration={result.duration_seconds:.3f}s"
        )
        
        # Log the final execution API response
        logger.info(f"Final execution API response: {api_response.model_dump()}")

        return api_response

    except ValueError as e:
        logger.warning(f"Invalid workflow definition: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow definition: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error during execution: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error during execution: {str(e)}"
        )


@router.get(
    "/executions/{run_id}",
    response_model=SimpleWorkflowExecutionResponse,
    summary="Get Execution Result",
    description="Retrieve the results of a specific workflow execution",
    response_description="Simplified execution results in standard API format"
)
async def get_execution_result(run_id: str) -> SimpleWorkflowExecutionResponse:
    """
    Get execution results for a specific run ID.

    Args:
        run_id: The execution run ID to retrieve

    Returns:
        WorkflowExecutionResponse: Complete execution results

    Raises:
        HTTPException: 404 if execution not found
    """
    if run_id not in _execution_results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution with run_id '{run_id}' not found"
        )
    
    result = _execution_results[run_id]
    return _convert_to_simple_execution_response(result)


@router.get(
    "/executions",
    response_model=WorkflowListResponse,
    summary="List Workflow Executions",
    description="Get a list of all workflow executions",
    response_description="List of workflow executions with summary info"
)
async def list_executions() -> WorkflowListResponse:
    """
    List all workflow executions.

    Returns:
        WorkflowListResponse: List of executions with metadata
    """
    executions = []
    for run_id, result in _execution_results.items():
        executions.append({
            "run_id": run_id,
            "workflow_id": result.workflow_id,
            "status": result.status,
            "success": result.success,
            "started_at": result.start_time.isoformat(),
            "duration_seconds": result.duration_seconds
        })
    
    return WorkflowListResponse(
        executions=executions,
        total_count=len(executions)
    )


@router.get(
    "/health",
    response_model=ExecutionHealthResponse,
    summary="Execution Service Health Check",
    description="Check the health and status of the workflow execution service",
    response_description="Current health status and service metrics"
)
async def get_execution_health() -> ExecutionHealthResponse:
    """
    Get health status of the execution service.

    Returns information about:
    - Service status and readiness
    - Runner instance status
    - Available executors
    - Active execution count

    Returns:
        ExecutionHealthResponse: Current service health information
    """
    try:
        runner = get_runner()
        
        # Get available executors
        available_executors = list(runner.registry.list_executors().keys())
        
        return ExecutionHealthResponse(
            status="healthy",
            runner_ready=True,
            active_executions=0,  # Could be enhanced with actual tracking
            total_executions=len(_execution_results),
            available_executors=available_executors
        )
    
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return ExecutionHealthResponse(
            status="unhealthy",
            runner_ready=False,
            active_executions=0,
            total_executions=0,
            available_executors=[]
        )


# Helper functions

def _convert_to_simple_execution_response(result: WorkflowExecutionResult) -> SimpleWorkflowExecutionResponse:
    """Convert WorkflowExecutionResult to simplified API response format with clean node array."""
    
    # Create a mapping of node IDs to node definitions for extracting names and types
    node_definitions = {}
    if hasattr(result, 'workflow_definition') and result.workflow_definition:
        nodes = result.workflow_definition.get('nodes', [])
        for node_def in nodes:
            node_id = node_def.get('id')
            node_definitions[node_id] = node_def
    
    # Convert node results to simplified array format
    nodes_array = []
    if result.node_results:
        for node_id, node_result in result.node_results.items():
            if node_result is not None:
                # Get node definition for name and type
                node_def = node_definitions.get(node_id, {})
                # Priority: name field first, then config.name, then node_id as fallback
                node_name = node_def.get('name', node_def.get('config', {}).get('name', node_id))
                node_type = node_def.get('type', 'unknown')
                
                # Safely extract execution data
                data = node_result.get('data', {}) if isinstance(node_result, dict) else {}
                status = node_result.get('status', 'unknown') if isinstance(node_result, dict) else 'unknown'
                error = node_result.get('error') if isinstance(node_result, dict) else None
                
                # Generate simple response text based on node type
                response_text = _extract_simple_response(node_type, data)
                
                # Create structured output from the execution data based on node definition
                structured_output = _create_structured_output(node_type, data, node_def)
                
                nodes_array.append(SimpleNodeResult(
                    node_id=node_id,
                    node_name=node_name,
                    node_type=node_type,
                    status=status,
                    response=response_text,
                    structured_output=structured_output,
                    error=error
                ))
    
    return SimpleWorkflowExecutionResponse(
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        status=result.status,
        success=result.success,
        started_at=result.start_time.isoformat(),
        finished_at=result.end_time.isoformat() if result.end_time else None,
        duration_seconds=result.duration_seconds,
        nodes=nodes_array
    )


def _convert_to_execution_response(result: WorkflowExecutionResult) -> WorkflowExecutionResponse:
    """Convert WorkflowExecutionResult to API response format."""
    
    # Create a mapping of node IDs to node definitions for extracting names and aliases
    node_definitions = {}
    if hasattr(result, 'workflow_definition') and result.workflow_definition:
        nodes = result.workflow_definition.get('nodes', [])
        for node_def in nodes:
            node_definitions[node_def.get('id')] = node_def
    
    # Convert node results with safe access and standardized format
    node_results = {}
    if result.node_results:
        for node_id, node_result in result.node_results.items():
            if node_result is not None:
                # Safely extract data
                data = node_result.get('data', {}) if isinstance(node_result, dict) else {}
                node_type = data.get('node_type', 'unknown') if isinstance(data, dict) else 'unknown'
                
                # Get node definition for name and alias
                node_def = node_definitions.get(node_id, {})
                node_name = node_def.get('config', {}).get('name', node_def.get('id', node_id))
                node_alias = node_def.get('alias', node_id)
                
                # Extract timing information
                started_at = None
                finished_at = None
                duration_ms = None
                
                if isinstance(node_result, dict):
                    # Try to get timing from various possible fields
                    started_at = node_result.get('started_at') or node_result.get('start_time')
                    finished_at = node_result.get('finished_at') or node_result.get('end_time')
                    duration_ms = node_result.get('duration_ms') or node_result.get('duration')
                    
                    # Convert datetime objects to ISO strings if needed
                    if started_at and hasattr(started_at, 'isoformat'):
                        started_at = started_at.isoformat()
                    if finished_at and hasattr(finished_at, 'isoformat'):
                        finished_at = finished_at.isoformat()
                
                node_results[node_id] = NodeExecutionResult(
                    node_id=node_id,
                    node_name=node_name,
                    node_type=node_type,
                    alias=node_alias,
                    status=node_result.get('status', 'unknown') if isinstance(node_result, dict) else 'unknown',
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    output=data if isinstance(data, dict) else {},
                    error=node_result.get('error') if isinstance(node_result, dict) else None
                )
    
    return WorkflowExecutionResponse(
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        status=result.status,
        success=result.success,
        started_at=result.start_time.isoformat(),
        finished_at=result.end_time.isoformat() if result.end_time else None,
        duration_seconds=result.duration_seconds,
        output=result.output,
        node_results=node_results,
        error=result.error
    )


def _extract_simple_response(node_type: str, data: dict) -> str:
    """Extract simple response text from node execution data based on node type."""
    if not isinstance(data, dict):
        return ""
    
    if node_type == "start":
        message = data.get('message', '')
        node_name = data.get('node_name', 'Start')
        return f"Workflow started at {node_name}"
    
    elif node_type == "end":
        message = data.get('message', '')
        node_name = data.get('node_name', 'End')
        return f"Workflow completed at {node_name}"
    
    elif node_type == "agent":
        # For agent nodes, extract the AI response
        if 'response' in data:
            response = data['response']
            # Truncate long responses for the simple text field
            if len(response) > 200:
                return response[:200] + "..."
            return response
        elif 'full' in data and isinstance(data['full'], dict):
            response = data['full'].get('response', '')
            if len(response) > 200:
                return response[:200] + "..."
            return response
        return "AI agent executed successfully"
    
    elif node_type == "mcp_tool":
        # For MCP tool nodes
        if 'result' in data:
            result_str = str(data['result'])
            if len(result_str) > 200:
                return result_str[:200] + "..."
            return result_str
        return "MCP tool executed successfully"
    
    elif node_type == "condition":
        # For condition nodes
        target = data.get('selected_target', 'unknown')
        return f"Condition evaluated, selected: {target}"
    
    else:
        # Default fallback
        if 'message' in data:
            return data['message']
        return f"Node executed successfully"


def _create_structured_output(node_type: str, data: dict, node_def: dict) -> dict:
    """Create structured output only when JSON schema is defined in node configuration."""
    if not isinstance(data, dict) or not isinstance(node_def, dict):
        return {}
    
    node_config = node_def.get('config', {})
    
    if node_type == "agent":
        # Check if agent has structured JSON output configured
        response_format = node_config.get('response_format', {})
        if response_format.get('type') == 'json_schema':
            # Agent has structured output defined - extract parsed response
            if 'parsed' in data:
                return data['parsed']  # This is the structured JSON mapped to schema keys
            elif 'full' in data and isinstance(data['full'], dict):
                # Fallback: try to get parsed response from full data
                full_data = data['full']
                if 'parsed' in full_data:
                    return full_data['parsed']
        
        # No structured output defined for this agent
        return {}
    
    elif node_type == "mcp_tool":
        # Check if MCP tool has JSON output configured
        output_format = node_config.get('output_format', 'auto')
        if output_format in ['json', 'json_object']:
            # MCP tool has structured output defined - extract result
            if 'result' in data:
                result = data['result']
                # If result is already parsed JSON, return it
                if isinstance(result, dict):
                    return result
                # If result is string that looks like JSON, it should have been parsed already
                # by the MCP executor, so just return the result as-is
                return {"result": result}
        
        # No structured output defined for this MCP tool
        return {}
    
    elif node_type == "condition":
        # Condition nodes could have structured output if they return complex evaluation results
        # For now, only return structured output if there's a specific configuration
        # This could be enhanced later based on condition node requirements
        return {}
    
    else:
        # Start, End, and other node types typically don't have structured output
        # unless specifically configured (which would be handled above)
        return {}


# Example usage and testing
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI
    
    # Create test app
    app = FastAPI(
        title="AI Workflow Engine API",
        description="REST API for executing AI workflows",
        version="1.0.0"
    )
    app.include_router(router)
    
    # Run the server
    print("Starting AI Workflow Engine API server...")
    print("API Documentation: http://localhost:8000/docs")
    print("Health Check: http://localhost:8000/api/v1/workflows/health")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)