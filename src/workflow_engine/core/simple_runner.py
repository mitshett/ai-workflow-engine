"""
Simple Workflow Runner - Basic workflow execution orchestrator

Provides a simple interface to execute workflows with agent nodes,
handling basic sequential execution and state management.

Author: AI Workflow Engine Team
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import structlog

from .context import ExecutionContext
from .node_executor import ExecutorRegistry, ExecutionStatus
from .parser import WorkflowDefinitionParser
from ..executors.start_executor import StartExecutor
from ..executors.end_executor import EndExecutor
from ..executors.agent_executor import AgentExecutor
from ..executors.condition_executor import ConditionExecutor
from ..executors.mcp_executor import MCPToolExecutor
from ..mcp.client_manager import MCPClientManager
from ..persistence.database import DatabaseManager

# Set up structured logging
logger = structlog.get_logger(__name__)


class WorkflowExecutionResult:
    """Result of workflow execution"""

    def __init__(
        self,
        run_id: str,
        workflow_id: str,
        status: str,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        node_results: Optional[Dict[str, Any]] = None,
        workflow_definition: Optional[Dict[str, Any]] = None
    ):
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.status = status
        self.start_time = start_time
        self.end_time = end_time
        self.output = output or {}
        self.error = error
        self.node_results = node_results or {}
        self.workflow_definition = workflow_definition

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get execution duration in seconds"""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def success(self) -> bool:
        """Check if workflow execution was successful"""
        return self.status == "completed"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "output": self.output,
            "error": self.error,
            "node_results": self.node_results,
            "success": self.success
        }


class SimpleWorkflowRunner:
    """
    Simple workflow runner for basic sequential execution.

    Supports agent nodes with Azure OpenAI integration and basic
    sequential workflow execution patterns.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None, mcp_client_manager: Optional[MCPClientManager] = None):
        """
        Initialize the workflow runner.

        Args:
            db_manager: Optional database manager for persistence
            mcp_client_manager: Optional MCP client manager for MCP tool nodes
        """
        self.db_manager = db_manager
        self.mcp_client_manager = mcp_client_manager or MCPClientManager()
        self._setup_executors()

    def _setup_executors(self):
        """Set up the executor registry with available executors"""
        self.registry = ExecutorRegistry()

        # Register core workflow executors
        self.registry.register("start", StartExecutor())
        self.registry.register("end", EndExecutor())
        self.registry.register("agent", AgentExecutor())
        self.registry.register("condition", ConditionExecutor())
        self.registry.register("mcp_tool", MCPToolExecutor(self.mcp_client_manager))

        logger.info("Workflow runner initialized", executors=self.registry.list_executors())

    async def run_workflow(
        self,
        workflow_definition: Dict[str, Any],
        input_data: Dict[str, Any],
        run_id: Optional[str] = None
    ) -> WorkflowExecutionResult:
        """
        Execute a workflow with the given input data.

        Args:
            workflow_definition: The workflow definition dictionary
            input_data: Input data for the workflow
            run_id: Optional run ID (generated if not provided)

        Returns:
            WorkflowExecutionResult with execution details
        """
        if not run_id:
            run_id = str(uuid.uuid4())

        workflow_id = workflow_definition.get("id", "unknown")
        start_time = datetime.now(timezone.utc)

        logger.info(
            "Starting workflow execution",
            run_id=run_id,
            workflow_id=workflow_id,
            input_keys=list(input_data.keys())
        )

        try:
            # 1. Parse and validate workflow
            parser = WorkflowDefinitionParser()
            parse_result = parser.parse_dict(workflow_definition)

            if not parse_result.is_valid:
                error_msg = f"Workflow validation failed: {'; '.join([e.message for e in parse_result.validation_result.errors])}"
                logger.error("Workflow validation failed", run_id=run_id, errors=[e.message for e in parse_result.validation_result.errors])

                return WorkflowExecutionResult(
                    run_id=run_id,
                    workflow_id=workflow_id,
                    status="failed",
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc),
                    error=error_msg,
                    workflow_definition=workflow_definition
                )

            workflow = parse_result.workflow
            logger.info("Workflow validation successful", run_id=run_id, node_count=len(workflow.nodes))

            # 2. Create execution context
            if self.db_manager:
                session = await self.db_manager.get_session()
            else:
                from unittest.mock import AsyncMock
                session = AsyncMock()

            # Build alias-to-node-id mapping from workflow nodes
            alias_to_node_mapping = {}
            for node in workflow.nodes:
                if hasattr(node, 'alias') and getattr(node, 'alias'):
                    alias_to_node_mapping[node.alias] = node.id

            context = ExecutionContext(run_id, session, alias_to_node_mapping=alias_to_node_mapping)
            logger.debug("Context initialized with aliases", run_id=run_id, aliases=list(alias_to_node_mapping.keys()))

            # 3. Initialize context with input data
            await context.set("workflow.input", input_data)
            await context.set("workflow.id", workflow_id)
            await context.set("workflow.started_at", start_time.isoformat())

            logger.debug("Context initialized", run_id=run_id, input_data=input_data)

            # 4. Execute workflow nodes in sequence
            node_results = {}
            current_node_id = self._find_start_node(workflow.nodes)

            if not current_node_id:
                raise ValueError("No start node found (node with no incoming connections)")

            executed_nodes = set()

            while current_node_id and current_node_id not in executed_nodes:
                # Find the node
                current_node = None
                for node in workflow.nodes:
                    if node.id == current_node_id:
                        current_node = node
                        break

                if not current_node:
                    raise ValueError(f"Node '{current_node_id}' not found in workflow definition")

                logger.info("Executing node", run_id=run_id, node_id=current_node_id, node_type=current_node.type)

                # Execute the node
                result = await self.registry.execute_node(current_node, context)

                # Store result
                node_results[current_node_id] = {
                    "status": result.status.value,
                    "data": result.data,
                    "error": result.error,
                    "duration_ms": result.metrics.duration_ms if result.metrics else None,
                    "logs": result.logs
                }

                # Check execution result
                if result.status != ExecutionStatus.SUCCESS:
                    error_msg = f"Node '{current_node_id}' failed: {result.error.get('message', 'Unknown error') if result.error else 'Unknown error'}"
                    logger.error("Node execution failed", run_id=run_id, node_id=current_node_id, error=error_msg)

                    return WorkflowExecutionResult(
                        run_id=run_id,
                        workflow_id=workflow_id,
                        status="failed",
                        start_time=start_time,
                        end_time=datetime.now(timezone.utc),
                        error=error_msg,
                        node_results=node_results,
                        workflow_definition=workflow_definition
                    )

                executed_nodes.add(current_node_id)
                logger.info("Node execution completed", run_id=run_id, node_id=current_node_id, status=result.status.value)

                # Determine next node - use result.next_nodes for conditional routing
                if result.next_nodes:
                    # Use next_nodes from execution result (for conditional routing)
                    current_node_id = result.next_nodes[0]  # Take first next node from result
                    logger.info("Using conditional routing", run_id=run_id, next_node=current_node_id, available_routes=result.next_nodes)
                elif current_node.next:
                    # Fallback to node.next for normal sequential execution
                    current_node_id = current_node.next[0]  # Take first next node
                    logger.info("Using sequential routing", run_id=run_id, next_node=current_node_id)
                else:
                    current_node_id = None  # End of workflow
                    logger.info("Workflow complete - no more nodes", run_id=run_id)

            # 5. Collect final output
            final_output = {}
            for node_id in executed_nodes:
                node_output = await context.get(f"nodes.{node_id}.output")
                if node_output is not None:
                    final_output[node_id] = node_output

            # Get the last node's output as the main workflow output
            if executed_nodes:
                last_node_id = list(executed_nodes)[-1]
                main_output = await context.get(f"nodes.{last_node_id}.output")
                if main_output is not None:
                    final_output["result"] = main_output

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            logger.info(
                "Workflow execution completed successfully",
                run_id=run_id,
                workflow_id=workflow_id,
                duration_seconds=duration,
                nodes_executed=len(executed_nodes)
            )

            return WorkflowExecutionResult(
                run_id=run_id,
                workflow_id=workflow_id,
                status="completed",
                start_time=start_time,
                end_time=end_time,
                output=final_output,
                node_results=node_results,
                workflow_definition=workflow_definition
            )

        except Exception as e:
            error_msg = f"Workflow execution failed: {str(e)}"
            logger.error("Workflow execution failed", run_id=run_id, error=str(e), error_type=type(e).__name__)

            return WorkflowExecutionResult(
                run_id=run_id,
                workflow_id=workflow_id,
                status="failed",
                start_time=start_time,
                end_time=datetime.now(timezone.utc),
                error=error_msg,
                workflow_definition=workflow_definition
            )

    def _find_start_node(self, nodes: List[Any]) -> Optional[str]:
        """Find the starting node (node with no incoming connections)"""
        # Collect all node IDs that are referenced as 'next'
        referenced_nodes = set()
        for node in nodes:
            if hasattr(node, 'next') and node.next:
                referenced_nodes.update(node.next)

        # Find nodes that are not referenced (start nodes)
        start_nodes = []
        for node in nodes:
            if hasattr(node, 'id') and node.id not in referenced_nodes:
                start_nodes.append(node.id)

        if len(start_nodes) == 1:
            return start_nodes[0]
        elif len(start_nodes) == 0:
            logger.warning("No start node found - all nodes are referenced")
            return None
        else:
            logger.warning("Multiple start nodes found", start_nodes=start_nodes)
            return start_nodes[0]  # Return first one

    async def validate_workflow(self, workflow_definition: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a workflow definition without executing it.

        Args:
            workflow_definition: The workflow definition to validate

        Returns:
            Dictionary with validation results
        """
        parser = WorkflowDefinitionParser()
        result = parser.parse_dict(workflow_definition)

        return {
            "is_valid": result.is_valid,
            "errors": [{"message": error.message, "details": getattr(error, 'details', None)} for error in result.validation_result.errors],
            "warnings": [{"message": warning, "details": None} for warning in result.validation_result.warnings],
            "node_count": len(result.workflow.nodes) if result.workflow else 0,
            "supported_node_types": list(self.registry.list_executors().keys())
        }


# Example usage and testing
async def run_simple_agent_workflow():
    """Example of running a simple agent workflow"""

    # Define a simple workflow with one agent node
    workflow_definition = {
        "id": "simple_greeting_workflow",
        "name": "Simple Greeting Workflow",
        "description": "A simple workflow that greets a user",
        "nodes": [
            {
                "id": "greet_user",
                "type": "agent",
                "config": {
                    "provider": "azure_openai",
                    "model": "gpt-35-turbo",
                    "prompt": "Say hello to ${workflow.input.user_name} and write a short ${workflow.input.content_type}",
                    "system_prompt": "You are a friendly AI assistant.",
                    "temperature": 0.7,
                    "max_tokens": 200
                },
                "next": []
            }
        ]
    }

    # Input data
    input_data = {
        "user_name": "Alice",
        "content_type": "poem"
    }

    # Create and run workflow
    runner = SimpleWorkflowRunner()

    print("🚀 Starting simple agent workflow execution...")
    print(f"Input: {input_data}")

    # Validate first
    validation = await runner.validate_workflow(workflow_definition)
    print(f"Validation: {validation}")

    if validation["is_valid"]:
        # Execute workflow
        result = await runner.run_workflow(workflow_definition, input_data)

        print(f"\n📊 Execution Results:")
        print(f"Status: {result.status}")
        print(f"Duration: {result.duration_seconds:.2f}s")

        if result.success:
            print(f"Output: {result.output}")
            print(f"Agent Response: {result.output.get('result', 'No response')}")
        else:
            print(f"Error: {result.error}")

        return result
    else:
        print("❌ Workflow validation failed")
        for error in validation["errors"]:
            print(f"  - {error['message']}")
        return None


async def run_multi_agent_workflow():
    """Example of running a workflow with multiple agent nodes"""

    workflow_definition = {
        "id": "multi_agent_workflow",
        "name": "Multi-Agent Workflow",
        "description": "A workflow with multiple connected agent nodes",
        "nodes": [
            {
                "id": "start_agent",
                "type": "agent",
                "config": {
                    "provider": "azure_openai",
                    "model": "gpt-35-turbo",
                    "prompt": "Analyze this request: ${workflow.input.request}. Provide key points.",
                    "system_prompt": "You are an analytical AI assistant.",
                    "temperature": 0.3,
                    "max_tokens": 300
                },
                "next": ["summary_agent"]
            },
            {
                "id": "summary_agent",
                "type": "agent",
                "config": {
                    "provider": "azure_openai",
                    "model": "gpt-35-turbo",
                    "prompt": "Based on this analysis: ${nodes.start_agent.output}, create a concise summary for ${workflow.input.audience}.",
                    "system_prompt": "You are a summarization expert.",
                    "temperature": 0.5,
                    "max_tokens": 200
                },
                "next": []
            }
        ]
    }

    input_data = {
        "request": "Help me understand the benefits of using AI in workflow automation",
        "audience": "business executives"
    }

    runner = SimpleWorkflowRunner()

    print("🚀 Starting multi-agent workflow execution...")
    print(f"Input: {input_data}")

    result = await runner.run_workflow(workflow_definition, input_data)

    print(f"\n📊 Multi-Agent Results:")
    print(f"Status: {result.status}")
    print(f"Duration: {result.duration_seconds:.2f}s")

    if result.success:
        print(f"Final Output: {result.output.get('result', 'No response')}")
        print(f"\nNode Results:")
        for node_id, node_result in result.node_results.items():
            print(f"  {node_id}: {node_result['status']}")
            if node_result['data']:
                response = node_result['data'].get('response', 'No response')
                print(f"    Response: {response[:100]}..." if len(response) > 100 else f"    Response: {response}")
    else:
        print(f"Error: {result.error}")

    return result


if __name__ == "__main__":
    # Test the simple workflow runner
    print("Testing Simple Workflow Runner with Azure OpenAI")
    print("=" * 50)

    # Run simple single-agent workflow
    asyncio.run(run_simple_agent_workflow())

    print("\n" + "=" * 50)

    # Run multi-agent workflow
    asyncio.run(run_multi_agent_workflow())