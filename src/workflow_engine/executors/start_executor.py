"""
StartExecutor - Workflow Start Node Execution

Implements the execution logic for workflow start nodes which serve as
entry points for workflows in enterprise workflow management systems.

Author: AI Workflow Engine Team
"""

from datetime import datetime, timezone
from typing import Dict, Any

from ..core.node_executor import (
    NodeExecutor,
    ExecutionResult,
    ExecutionStatus,
    ExecutionMetrics,
    ValidationResult
)
from ..core.context import ExecutionContext
from ..core.schemas import WorkflowNode

# Set up structured logging
from ..shared.utils.logging import get_logger
logger = get_logger(__name__)


class StartExecutor(NodeExecutor):
    """
    Executor for workflow start nodes.
    
    Start nodes serve as entry points for workflows and handle:
    - Workflow initialization
    - Input validation and preparation
    - Initial context setup
    - Workflow metadata recording
    """

    NODE_TYPE = "start"

    def __init__(self):
        super().__init__(default_timeout=30)  # Start nodes should be fast

    async def execute_impl(self, node: WorkflowNode, context: ExecutionContext) -> ExecutionResult:
        """Execute workflow start node"""
        
        start_time = datetime.now(timezone.utc)
        
        try:
            logger.info(
                "Executing start node",
                node_id=node.id,
                workflow_id=await context.get("workflow.id")
            )

            # Get configuration
            config = node.config or {}
            node_name = config.get("name", f"Start: {node.id}")
            node_description = config.get("description", "Workflow entry point")
            
            # Record workflow start in context
            workflow_start_time = start_time.isoformat()
            await context.set("workflow.started_at", workflow_start_time)
            await context.set("workflow.current_node", node.id)
            
            # Record start node metadata
            start_metadata = {
                "node_id": node.id,
                "node_name": node_name,
                "node_description": node_description,
                "started_at": workflow_start_time,
                "node_type": "start"
            }
            
            # Store node-specific output
            await context.set(f"nodes.{node.id}.started_at", workflow_start_time)
            await context.set(f"nodes.{node.id}.metadata", start_metadata)

            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            
            # Prepare result data
            result_data = {
                "message": f"Workflow started successfully at node: {node_name}",
                "started_at": workflow_start_time,
                "node_name": node_name,
                "node_description": node_description,
                "metadata": start_metadata
            }

            # Context updates for downstream nodes
            context_updates = {
                f"nodes.{node.id}.output": result_data,
                f"nodes.{node.id}.status": "completed"
            }

            logger.info(
                "Start node execution completed successfully",
                node_id=node.id,
                node_name=node_name,
                duration_ms=metrics.duration_ms
            )

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                data=result_data,
                metrics=metrics,
                context_updates=context_updates
            )

        except Exception as e:
            logger.error(
                "Start node execution failed",
                node_id=node.id,
                error=str(e),
                error_type=type(e).__name__
            )

            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()

            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                metrics=metrics
            )
            result.set_error(e, f"Start node execution failed for node {node.id}")
            return result

    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate start node configuration"""
        result = ValidationResult(is_valid=True)

        # Start nodes have minimal configuration requirements
        # Just validate optional fields if present
        
        if "name" in config:
            if not isinstance(config["name"], str) or len(config["name"].strip()) == 0:
                result.add_error(
                    "Start node name must be a non-empty string",
                    field="name"
                )

        if "description" in config:
            if not isinstance(config["description"], str):
                result.add_error(
                    "Start node description must be a string",
                    field="description"
                )

        if "metadata" in config:
            if not isinstance(config["metadata"], dict):
                result.add_error(
                    "Start node metadata must be a dictionary",
                    field="metadata"
                )

        return result

    def get_retry_policy(self):
        """Get retry policy for start node execution"""
        from ..core.node_executor import RetryPolicy

        # Start nodes should rarely fail, but if they do, retry quickly
        return RetryPolicy(
            max_attempts=2,
            base_delay_seconds=1.0,
            exponential_backoff=False,
            retry_on_timeout=True,
            retry_on_network_error=False,  # Start nodes don't make network calls
            retry_on_rate_limit=False,
            retry_on_server_error=False,
            retry_on_authentication_error=False,
            retry_on_validation_error=False  # Config should be validated upfront
        )


# Convenience function for testing
async def test_start_executor():
    """Test function for StartExecutor"""
    from unittest.mock import AsyncMock
    from ..core.context import ExecutionContext

    # Create mock context
    mock_session = AsyncMock()
    context = ExecutionContext("test_run")

    # Set up test workflow data
    await context.set("workflow.id", "test_workflow")
    await context.set("workflow.name", "Test Workflow")

    # Create start executor
    executor = StartExecutor()

    # Create test start node
    test_node = WorkflowNode(
        id="start_node",
        type="start",
        config={
            "name": "Workflow Start",
            "description": "Entry point for test workflow",
            "metadata": {"version": "1.0"}
        },
        next=["next_node"]
    )

    # Execute
    result = await executor.execute(test_node, context)

    print(f"Start Node Execution Status: {result.status}")
    print(f"Start Message: {result.data.get('message', 'No message') if result.data else 'No data'}")
    print(f"Started At: {result.data.get('started_at', 'No timestamp') if result.data else 'No timestamp'}")

    return result


if __name__ == "__main__":
    # Run test
    import asyncio
    asyncio.run(test_start_executor())