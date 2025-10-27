"""
EndExecutor - Workflow End Node Execution

Implements the execution logic for workflow end nodes which serve as
termination points for workflows in enterprise workflow management systems.

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


class EndExecutor(NodeExecutor):
    """
    Executor for workflow end nodes.
    
    End nodes serve as termination points for workflows and handle:
    - Workflow finalization
    - Output collection and aggregation
    - Final context cleanup
    - Workflow completion metadata
    """

    NODE_TYPE = "end"

    def __init__(self):
        super().__init__(default_timeout=30)  # End nodes should be fast

    async def execute_impl(self, node: WorkflowNode, context: ExecutionContext) -> ExecutionResult:
        """Execute workflow end node"""
        
        start_time = datetime.now(timezone.utc)
        
        try:
            logger.info(
                "Executing end node",
                node_id=node.id,
                workflow_id=await context.get("workflow.id")
            )

            # Get configuration
            config = node.config or {}
            node_name = config.get("name", f"End: {node.id}")
            node_description = config.get("description", "Workflow completion point")
            collect_outputs = config.get("collect_outputs", True)
            
            # Record workflow end in context
            workflow_end_time = start_time.isoformat()
            workflow_started_at = await context.get("workflow.started_at")
            
            await context.set("workflow.finished_at", workflow_end_time)
            await context.set("workflow.status", "completed")
            await context.set("workflow.current_node", node.id)
            
            # Collect workflow outputs if requested
            collected_outputs = {}
            if collect_outputs:
                # Get all available keys in the context
                all_keys = await context.get_all_keys()
                
                # Extract node outputs
                for key in all_keys:
                    if key.startswith("nodes.") and key.endswith(".output"):
                        node_id = key.replace("nodes.", "").replace(".output", "")
                        if node_id != node.id:  # Don't include self
                            value = await context.get(key)
                            if value is not None:
                                collected_outputs[node_id] = value

            # Calculate workflow duration if we have start time
            workflow_duration_seconds = None
            if workflow_started_at:
                try:
                    start_dt = datetime.fromisoformat(workflow_started_at.replace('Z', '+00:00'))
                    end_dt = start_time
                    workflow_duration_seconds = (end_dt - start_dt).total_seconds()
                except Exception as e:
                    logger.warning(f"Could not calculate workflow duration - error: {str(e)}")

            # Record end node metadata
            end_metadata = {
                "node_id": node.id,
                "node_name": node_name,
                "node_description": node_description,
                "finished_at": workflow_end_time,
                "node_type": "end",
                "workflow_duration_seconds": workflow_duration_seconds,
                "outputs_collected": len(collected_outputs) if collect_outputs else 0
            }
            
            # Store node-specific output
            await context.set(f"nodes.{node.id}.finished_at", workflow_end_time)
            await context.set(f"nodes.{node.id}.metadata", end_metadata)

            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            
            # Prepare result data
            result_data = {
                "message": f"Workflow completed successfully at node: {node_name}",
                "finished_at": workflow_end_time,
                "node_name": node_name,
                "node_description": node_description,
                "workflow_duration_seconds": workflow_duration_seconds,
                "metadata": end_metadata
            }

            # Include collected outputs if enabled
            if collect_outputs:
                result_data["collected_outputs"] = collected_outputs
                result_data["output_summary"] = {
                    "total_nodes": len(collected_outputs),
                    "node_ids": list(collected_outputs.keys())
                }

            # Context updates
            context_updates = {
                f"nodes.{node.id}.output": result_data,
                f"nodes.{node.id}.status": "completed",
                "workflow.final_output": result_data,
                "workflow.collected_outputs": collected_outputs if collect_outputs else {}
            }

            logger.info(
                "End node execution completed successfully",
                node_id=node.id,
                node_name=node_name,
                workflow_duration_seconds=workflow_duration_seconds,
                outputs_collected=len(collected_outputs) if collect_outputs else 0,
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
                "End node execution failed",
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
            result.set_error(e, f"End node execution failed for node {node.id}")
            return result

    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate end node configuration"""
        result = ValidationResult(is_valid=True)

        # End nodes have minimal configuration requirements
        # Validate optional fields if present
        
        if "name" in config:
            if not isinstance(config["name"], str) or len(config["name"].strip()) == 0:
                result.add_error(
                    "End node name must be a non-empty string",
                    field="name"
                )

        if "description" in config:
            if not isinstance(config["description"], str):
                result.add_error(
                    "End node description must be a string",
                    field="description"
                )

        if "metadata" in config:
            if not isinstance(config["metadata"], dict):
                result.add_error(
                    "End node metadata must be a dictionary",
                    field="metadata"
                )

        if "collect_outputs" in config:
            if not isinstance(config["collect_outputs"], bool):
                result.add_error(
                    "collect_outputs must be a boolean value",
                    field="collect_outputs"
                )

        return result

    def get_retry_policy(self):
        """Get retry policy for end node execution"""
        from ..core.node_executor import RetryPolicy

        # End nodes should rarely fail, but if they do, retry quickly
        return RetryPolicy(
            max_attempts=2,
            base_delay_seconds=1.0,
            exponential_backoff=False,
            retry_on_timeout=True,
            retry_on_network_error=False,  # End nodes don't make network calls
            retry_on_rate_limit=False,
            retry_on_server_error=False,
            retry_on_authentication_error=False,
            retry_on_validation_error=False  # Config should be validated upfront
        )


# Convenience function for testing
async def test_end_executor():
    """Test function for EndExecutor"""
    from unittest.mock import AsyncMock
    from ..core.context import ExecutionContext

    # Create mock context
    mock_session = AsyncMock()
    context = ExecutionContext("test_run")

    # Set up test workflow data with some sample outputs
    await context.set("workflow.id", "test_workflow")
    await context.set("workflow.name", "Test Workflow")
    await context.set("workflow.started_at", "2024-01-01T10:00:00Z")
    
    # Add some sample node outputs
    await context.set("nodes.start_node.output", {"message": "Workflow started"})
    await context.set("nodes.agent_node.output", {"response": "Sample AI response"})

    # Create end executor
    executor = EndExecutor()

    # Create test end node
    test_node = WorkflowNode(
        id="end_node",
        type="end",
        config={
            "name": "Workflow End",
            "description": "Completion point for test workflow",
            "collect_outputs": True,
            "metadata": {"version": "1.0"}
        },
        next=[]
    )

    # Execute
    result = await executor.execute(test_node, context)

    print(f"End Node Execution Status: {result.status}")
    print(f"End Message: {result.data.get('message', 'No message') if result.data else 'No data'}")
    print(f"Workflow Duration: {result.data.get('workflow_duration_seconds', 'No duration') if result.data else 'No duration'}s")
    print(f"Collected Outputs: {result.data.get('output_summary', 'No outputs') if result.data else 'No outputs'}")

    return result


if __name__ == "__main__":
    # Run test
    import asyncio
    asyncio.run(test_end_executor())