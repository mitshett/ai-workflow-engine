"""
Execution service for the AI Workflow Engine.

This service handles the core workflow execution logic including:
- DAG traversal and topological ordering
- Node execution coordination  
- Parallel execution management
- Error handling and retry logic
- Context state management

Author: AI Workflow Engine Team
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from ..domain.models import (
    Workflow,
    Node,
    ExecutionResult,
    ExecutionContext,
    NodeResult,
    create_node_result,
)
from ..domain.enums.execution_status import ExecutionStatus, NodeExecutionStatus
from ..domain.enums.node_types import NodeType, TriggerRule
from ..domain.exceptions.base import (
    ExecutionError,
    BusinessLogicException
)


class ExecutionService:
    """
    Workflow execution orchestration service.
    
    This service manages the complete execution lifecycle of workflows:
    - Determines execution order using topological sorting
    - Manages parallel and sequential node execution
    - Handles context updates and state management
    - Coordinates error handling and recovery
    """
    
    def __init__(
        self,
        executor_registry_service: 'NodeExecutorRegistryService',
        max_parallel_nodes: int = 10,
        default_timeout_seconds: int = 300
    ):
        """
        Initialize the execution service.
        
        Args:
            executor_registry_service: Service for managing node executors
            max_parallel_nodes: Maximum nodes to execute in parallel
            default_timeout_seconds: Default node execution timeout
        """
        self.executor_registry_service = executor_registry_service
        self.max_parallel_nodes = max_parallel_nodes
        self.default_timeout_seconds = default_timeout_seconds
        self.logger = logging.getLogger(__name__)
        
        # Track active executions for cancellation support
        self._active_executions: Dict[str, asyncio.Task] = {}
        self._execution_lock = asyncio.Lock()
    
    async def execute_workflow(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        execution_result: ExecutionResult,
        options: Dict[str, Any] = None
    ) -> ExecutionResult:
        """
        Execute a complete workflow.
        
        Args:
            workflow: Workflow domain object to execute
            context: Execution context for state management
            execution_result: Execution result object to populate
            options: Optional execution configuration
            
        Returns:
            Completed ExecutionResult with all node results
            
        Raises:
            ExecutionError: If execution fails
            BusinessLogicException: If workflow structure is invalid
        """
        run_id = execution_result.run_id
        options = options or {}
        
        self.logger.info(
            "Starting workflow execution",
            extra={
                "workflow_id": workflow.id,
                "run_id": run_id,
                "node_count": workflow.node_count,
                "max_parallel": options.get('max_parallel_nodes', self.max_parallel_nodes)
            }
        )
        
        try:
            # Register execution for cancellation support
            execution_task = asyncio.current_task()
            async with self._execution_lock:
                self._active_executions[run_id] = execution_task
            
            # Validate workflow structure
            if not workflow.is_valid:
                validation_errors = workflow.validate_structure()
                raise BusinessLogicException(
                    f"Invalid workflow structure: {validation_errors}",
                    rule="valid_workflow_structure",
                    details={"validation_errors": validation_errors}
                )
            
            # Get execution plan
            execution_plan = await self._create_execution_plan(workflow)
            
            self.logger.info(
                "Execution plan created",
                extra={
                    "workflow_id": workflow.id,
                    "run_id": run_id,
                    "execution_batches": len(execution_plan),
                    "total_nodes": sum(len(batch) for batch in execution_plan)
                }
            )
            
            # Execute workflow in batches
            execution_result.status = ExecutionStatus.RUNNING
            
            for batch_index, node_batch in enumerate(execution_plan):
                batch_result = await self._execute_node_batch(
                    node_batch=node_batch,
                    workflow=workflow,
                    context=context,
                    execution_result=execution_result,
                    batch_index=batch_index,
                    options=options
                )
                
                # Check if execution should stop
                if not batch_result.should_continue:
                    break
            
            # Finalize execution result
            await self._finalize_execution(execution_result, context)
            
            self.logger.info(
                "Workflow execution completed",
                extra={
                    "workflow_id": workflow.id,
                    "run_id": run_id,
                    "status": execution_result.status.value,
                    "success_rate": execution_result.success_rate,
                    "duration_seconds": execution_result.duration_seconds
                }
            )
            
        except asyncio.CancelledError:
            # Handle cancellation
            execution_result.mark_cancelled()
            self.logger.info(
                "Workflow execution cancelled",
                extra={"workflow_id": workflow.id, "run_id": run_id}
            )
            
        except Exception as e:
            # Handle execution failure
            execution_error = self._create_execution_error(e, workflow.id, run_id)
            execution_result.mark_failed(execution_error)
            
            self.logger.error(
                "Workflow execution failed",
                extra={
                    "workflow_id": workflow.id,
                    "run_id": run_id,
                    "error": str(e),
                    "error_type": e.__class__.__name__
                }
            )
            
        finally:
            # Cleanup execution tracking
            async with self._execution_lock:
                self._active_executions.pop(run_id, None)
        
        return execution_result
    
    async def cancel_execution(self, run_id: str) -> bool:
        """
        Cancel a running workflow execution.
        
        Args:
            run_id: Execution run identifier
            
        Returns:
            True if execution was cancelled, False if not found
        """
        async with self._execution_lock:
            execution_task = self._active_executions.get(run_id)
            
            if execution_task and not execution_task.done():
                execution_task.cancel()
                
                self.logger.info(
                    "Execution cancellation requested",
                    extra={"run_id": run_id}
                )
                
                return True
        
        return False
    
    async def _create_execution_plan(self, workflow: Workflow) -> List[List[str]]:
        """
        Create execution plan using topological sorting.
        
        Args:
            workflow: Workflow to create plan for
            
        Returns:
            List of node ID batches for execution
        """
        # Build dependency graph
        node_dependencies = {}
        for node in workflow.nodes:
            node_dependencies[node.id] = set(node.depends_on)
        
        # Topological sort with parallel batching
        execution_plan = []
        remaining_nodes = set(node.id for node in workflow.nodes)
        
        while remaining_nodes:
            # Find nodes with no remaining dependencies
            ready_nodes = []
            for node_id in remaining_nodes:
                if not node_dependencies[node_id]:
                    ready_nodes.append(node_id)
            
            if not ready_nodes:
                # Should not happen with valid DAG
                remaining_node_deps = {
                    node_id: list(deps) 
                    for node_id, deps in node_dependencies.items() 
                    if node_id in remaining_nodes and deps
                }
                raise BusinessLogicException(
                    "Circular dependency detected in workflow",
                    rule="no_circular_dependencies",
                    details={"remaining_dependencies": remaining_node_deps}
                )
            
            # Add batch to execution plan
            execution_plan.append(ready_nodes)
            
            # Remove ready nodes from remaining and dependencies
            for node_id in ready_nodes:
                remaining_nodes.remove(node_id)
                
                # Remove this node from other nodes' dependencies
                for deps in node_dependencies.values():
                    deps.discard(node_id)
        
        return execution_plan
    
    async def _execute_node_batch(
        self,
        node_batch: List[str],
        workflow: Workflow,
        context: ExecutionContext,
        execution_result: ExecutionResult,
        batch_index: int,
        options: Dict[str, Any]
    ) -> 'BatchExecutionResult':
        """
        Execute a batch of nodes in parallel.
        
        Args:
            node_batch: List of node IDs to execute
            workflow: Workflow being executed
            context: Execution context
            execution_result: Execution result to update
            batch_index: Index of current batch
            options: Execution options
            
        Returns:
            BatchExecutionResult with execution status
        """
        max_parallel = min(
            options.get('max_parallel_nodes', self.max_parallel_nodes),
            len(node_batch)
        )
        
        self.logger.info(
            "Executing node batch",
            extra={
                "workflow_id": workflow.id,
                "run_id": execution_result.run_id,
                "batch_index": batch_index,
                "batch_size": len(node_batch),
                "max_parallel": max_parallel
            }
        )
        
        # Check trigger rules before execution
        executable_nodes = []
        for node_id in node_batch:
            node = workflow.get_node_by_id(node_id)
            if node and await self._should_execute_node(node, context):
                executable_nodes.append(node)
            else:
                # Mark as skipped
                node_result = create_node_result(
                    node_id=node_id,
                    node_type=node.type if node else NodeType.START,
                    started_at=datetime.utcnow()
                )
                node_result.status = NodeExecutionStatus.SKIPPED
                node_result.finished_at = datetime.utcnow()
                
                context.add_node_result(node_result)
                execution_result.add_node_result(node_result)
        
        if not executable_nodes:
            return BatchExecutionResult(should_continue=True, all_successful=True)
        
        # Execute nodes with controlled parallelism
        semaphore = asyncio.Semaphore(max_parallel)
        tasks = []
        
        for node in executable_nodes:
            task = asyncio.create_task(
                self._execute_single_node_with_semaphore(
                    semaphore, node, workflow, context, execution_result, options
                )
            )
            tasks.append(task)
        
        # Wait for all tasks to complete
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process batch results
        successful_count = 0
        failed_count = 0
        should_continue = True
        
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                failed_count += 1
                self.logger.error(
                    "Node execution failed with exception",
                    extra={
                        "node_id": executable_nodes[i].id,
                        "error": str(result),
                        "error_type": result.__class__.__name__
                    }
                )
            elif result and result.is_successful:
                successful_count += 1
            else:
                failed_count += 1
        
        # Determine if execution should continue
        continue_on_failure = options.get('continue_on_failure', False)
        if failed_count > 0 and not continue_on_failure:
            should_continue = False
        
        self.logger.info(
            "Node batch execution completed",
            extra={
                "batch_index": batch_index,
                "successful_count": successful_count,
                "failed_count": failed_count,
                "should_continue": should_continue
            }
        )
        
        return BatchExecutionResult(
            should_continue=should_continue,
            all_successful=failed_count == 0,
            successful_count=successful_count,
            failed_count=failed_count
        )
    
    async def _execute_single_node_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        node: Node,
        workflow: Workflow,
        context: ExecutionContext,
        execution_result: ExecutionResult,
        options: Dict[str, Any]
    ) -> Optional[NodeResult]:
        """
        Execute a single node with semaphore control.
        
        Args:
            semaphore: Semaphore for controlling parallelism
            node: Node to execute
            workflow: Workflow being executed
            context: Execution context
            execution_result: Execution result to update
            options: Execution options
            
        Returns:
            NodeResult if successful, None if failed
        """
        async with semaphore:
            return await self._execute_single_node(
                node, workflow, context, execution_result, options
            )
    
    async def _execute_single_node(
        self,
        node: Node,
        workflow: Workflow,
        context: ExecutionContext,
        execution_result: ExecutionResult,
        options: Dict[str, Any]
    ) -> Optional[NodeResult]:
        """
        Execute a single node.
        
        Args:
            node: Node to execute
            workflow: Workflow being executed
            context: Execution context
            execution_result: Execution result to update
            options: Execution options
            
        Returns:
            NodeResult if successful, None if failed
        """
        start_time = datetime.utcnow()
        
        self.logger.info(
            "Starting node execution",
            extra={
                "node_id": node.id,
                "node_type": node.type.value,
                "workflow_id": workflow.id,
                "run_id": context.run_id
            }
        )
        
        # Create node result
        node_result = create_node_result(
            node_id=node.id,
            node_type=node.type,
            started_at=start_time
        )
        node_result.status = NodeExecutionStatus.RUNNING
        
        # Add to context and execution result
        context.add_node_result(node_result)
        execution_result.add_node_result(node_result)
        
        try:
            # Execute node using the registry service - CLEAN ARCHITECTURE
            domain_result = await self.executor_registry_service.execute_node(
                node=node,
                context=context
            )
            
            # The registry service returns a properly converted NodeResult
            # Update the existing node_result with the domain result data
            node_result.status = domain_result.status
            node_result.finished_at = domain_result.finished_at
            node_result.data = domain_result.data
            node_result.output = domain_result.output
            node_result.error = domain_result.error
            node_result.metrics = domain_result.metrics
            node_result.attempts = domain_result.attempts
            
            self.logger.info(
                "Node execution completed successfully",
                extra={
                    "node_id": node.id,
                    "duration_seconds": node_result.duration_seconds,
                    "has_output": node_result.has_output
                }
            )
            
            return node_result
                
        except Exception as e:
            # Handle execution error
            execution_error = self._create_execution_error(e, workflow.id, context.run_id, node.id)
            node_result.mark_failed(execution_error)
            
            self.logger.error(
                "Node execution failed",
                extra={
                    "node_id": node.id,
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "duration_seconds": node_result.duration_seconds
                }
            )
            
            return None
    
    async def _should_execute_node(self, node: Node, context: ExecutionContext) -> bool:
        """
        Check if a node should be executed based on trigger rules.
        
        Args:
            node: Node to check
            context: Execution context
            
        Returns:
            True if node should be executed
        """
        if not node.depends_on:
            # No dependencies, always execute
            return True
        
        trigger_rule = node.trigger_rule
        dependency_results = []
        
        for dep_node_id in node.depends_on:
            dep_result = context.get_node_result(dep_node_id)
            if dep_result:
                dependency_results.append(dep_result)
        
        if len(dependency_results) != len(node.depends_on):
            # Not all dependencies have results yet
            return False
        
        if trigger_rule == TriggerRule.ALL_SUCCESS:
            return all(result.is_successful for result in dependency_results)
        elif trigger_rule == TriggerRule.ONE_SUCCESS:
            return any(result.is_successful for result in dependency_results)
        elif trigger_rule == TriggerRule.ALL_DONE:
            return all(result.is_completed for result in dependency_results)
        elif trigger_rule == TriggerRule.ALWAYS:
            return True
        elif trigger_rule == TriggerRule.NONE_FAILED:
            return not any(result.is_failed for result in dependency_results)
        else:
            # Default to all success
            return all(result.is_successful for result in dependency_results)
    
    async def _finalize_execution(
        self,
        execution_result: ExecutionResult,
        context: ExecutionContext
    ) -> None:
        """
        Finalize execution result with final status and metrics.
        
        Args:
            execution_result: Execution result to finalize
            context: Execution context
        """
        # Determine final status
        if execution_result.status == ExecutionStatus.RUNNING:
            if execution_result.success_rate == 1.0:
                execution_result.mark_completed()
            else:
                # Some nodes failed
                final_error = self._create_execution_error(
                    Exception(f"Workflow failed: {execution_result.success_rate:.1%} success rate"),
                    execution_result.workflow_id,
                    execution_result.run_id
                )
                execution_result.mark_failed(final_error)
        
        # Update final metrics
        if execution_result.node_results:
            total_retries = sum(result.metrics.retries_count for result in execution_result.node_results)
            execution_result.metrics.retries_count = total_retries
            
            # Calculate average memory usage if available
            memory_usages = [
                result.metrics.memory_usage_mb 
                for result in execution_result.node_results 
                if result.metrics.memory_usage_mb is not None
            ]
            if memory_usages:
                execution_result.metrics.memory_usage_mb = sum(memory_usages) / len(memory_usages)
    
    def _create_execution_error(
        self,
        exception: Exception,
        workflow_id: str,
        run_id: str,
        node_id: Optional[str] = None
    ) -> 'ExecutionError':
        """
        Create ExecutionError from exception.
        
        Args:
            exception: Source exception
            workflow_id: Workflow identifier
            run_id: Run identifier
            node_id: Optional node identifier
            
        Returns:
            ExecutionError domain object
        """
        from ..domain.models.execution import ExecutionError
        
        error_type = exception.__class__.__name__
        error_code = getattr(exception, 'code', 'EXECUTION_ERROR')
        message = str(exception)
        
        details = {
            'workflow_id': workflow_id,
            'run_id': run_id,
            'original_exception': error_type
        }
        
        if node_id:
            details['node_id'] = node_id
        
        return ExecutionError(
            error_type=error_type,
            error_code=error_code,
            message=message,
            details=details,
            node_id=node_id,
            is_retryable=self._is_retryable_error(exception)
        )
    
    def _is_retryable_error(self, exception: Exception) -> bool:
        """
        Determine if an error is retryable.
        
        Args:
            exception: Exception to check
            
        Returns:
            True if error is retryable
        """
        retryable_types = [
            'ConnectionError',
            'TimeoutError',
            'TemporaryFailure',
            'ServiceUnavailable',
            'RateLimitError'
        ]
        
        return exception.__class__.__name__ in retryable_types


class BatchExecutionResult:
    """
    Result of executing a batch of nodes.
    
    Contains information about whether execution should continue
    and statistics about the batch execution.
    """
    
    def __init__(
        self,
        should_continue: bool,
        all_successful: bool,
        successful_count: int = 0,
        failed_count: int = 0
    ):
        self.should_continue = should_continue
        self.all_successful = all_successful
        self.successful_count = successful_count
        self.failed_count = failed_count
    
    @property
    def total_count(self) -> int:
        """Get total number of nodes in batch."""
        return self.successful_count + self.failed_count
    
    @property
    def success_rate(self) -> float:
        """Get success rate for the batch."""
        if self.total_count == 0:
            return 1.0
        return self.successful_count / self.total_count