"""
Core workflow orchestration service for the AI Workflow Engine.

This service contains the main business logic for workflow management,
orchestration, and execution coordination. It serves as the central
service that coordinates between validation, execution, and persistence.

Author: AI Workflow Engine Team
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from ..shared.utils.logging import get_logger

from ..domain.models import (
    Workflow,
    Node,
    ExecutionResult,
    ExecutionContext,
    create_execution_context,
    create_execution_result,
)
from ..domain.enums.execution_status import ExecutionStatus
from ..domain.exceptions.base import (
    ValidationError,
    ExecutionError,
    BusinessLogicException,
    ResourceNotFoundException,
)

logger = get_logger(__name__)


class WorkflowService:
    """
    Core workflow business logic service.
    
    This service orchestrates the complete workflow lifecycle including:
    - Workflow validation and parsing
    - Execution coordination 
    - State management
    - Error handling and recovery
    
    It follows the Clean Architecture pattern by containing pure business
    logic without dependencies on external frameworks or infrastructure.
    """
    
    def __init__(
        self,
        execution_service: 'ExecutionService',
        validation_service: 'ValidationService',
        workflow_repository: 'WorkflowRepository' = None
    ):
        """
        Initialize the workflow service.
        
        Args:
            execution_service: Service for managing workflow execution
            validation_service: Service for workflow validation
            workflow_repository: Optional repository for workflow persistence
        """
        self.execution_service = execution_service
        self.validation_service = validation_service
        self.workflow_repository = workflow_repository
        self.logger = logging.getLogger(__name__)
    
    async def create_workflow(
        self,
        name: str,
        definition: Dict[str, Any],
        description: Optional[str] = None,
        workflow_id: Optional[str] = None
    ) -> Workflow:
        """
        Create a new workflow from definition.
        
        Args:
            name: Human-readable workflow name
            definition: Workflow definition dictionary 
            description: Optional workflow description
            workflow_id: Optional custom workflow ID
            
        Returns:
            Validated Workflow domain object
            
        Raises:
            ValidationError: If workflow definition is invalid
        """
        self.logger.info(
            "Creating new workflow",
            extra={
                "workflow_name": name,
                "definition_keys": list(definition.keys()),
                "has_custom_id": workflow_id is not None
            }
        )
        
        try:
            # Parse and validate the workflow definition
            workflow = await self.validation_service.parse_and_validate_workflow(
                definition=definition,
                name=name,
                description=description,
                workflow_id=workflow_id
            )
            
            # Persist workflow if repository available
            if self.workflow_repository:
                await self.workflow_repository.save_workflow(workflow)
                self.logger.info(
                    "Workflow created and persisted",
                    extra={"workflow_id": workflow.id, "node_count": workflow.node_count}
                )
            else:
                self.logger.info(
                    "Workflow created (not persisted)",
                    extra={"workflow_id": workflow.id, "node_count": workflow.node_count}
                )
            
            return workflow
            
        except Exception as e:
            self.logger.error(
                "Failed to create workflow",
                extra={
                    "workflow_name": name,
                    "error": str(e),
                    "error_type": e.__class__.__name__
                }
            )
            raise
    
    async def get_workflow(self, workflow_id: str) -> Workflow:
        """
        Retrieve a workflow by ID.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Workflow domain object
            
        Raises:
            ResourceNotFoundException: If workflow not found
        """
        if not self.workflow_repository:
            raise BusinessLogicException(
                "Cannot retrieve workflow: no repository configured",
                rule="repository_required"
            )
        
        workflow = await self.workflow_repository.get_workflow(workflow_id)
        if not workflow:
            raise ResourceNotFoundException(
                f"Workflow not found: {workflow_id}",
                resource_type="workflow",
                resource_id=workflow_id
            )
        
        return workflow
    
    async def update_workflow(
        self,
        workflow_id: str,
        updates: Dict[str, Any]
    ) -> Workflow:
        """
        Update an existing workflow.
        
        Args:
            workflow_id: Workflow identifier
            updates: Dictionary of updates to apply
            
        Returns:
            Updated Workflow domain object
            
        Raises:
            ResourceNotFoundException: If workflow not found
            ValidationError: If updates are invalid
        """
        # Get existing workflow
        workflow = await self.get_workflow(workflow_id)
        
        # Apply updates (simple implementation - could be more sophisticated)
        if 'name' in updates:
            workflow.name = updates['name']
        if 'description' in updates:
            workflow.description = updates['description']
        if 'nodes' in updates:
            # Re-validate entire workflow with new nodes
            definition = workflow.to_dict()
            definition.update(updates)
            workflow = await self.validation_service.parse_and_validate_workflow(
                definition=definition,
                name=workflow.name,
                description=workflow.description,
                workflow_id=workflow.id
            )
        
        # Update metadata
        workflow.metadata.update_timestamp()
        
        # Persist changes
        if self.workflow_repository:
            await self.workflow_repository.save_workflow(workflow)
        
        self.logger.info(
            "Workflow updated",
            extra={
                "workflow_id": workflow_id,
                "update_keys": list(updates.keys()),
                "node_count": workflow.node_count
            }
        )
        
        return workflow
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """
        Delete a workflow.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            True if workflow was deleted, False if not found
            
        Raises:
            BusinessLogicException: If workflow has active executions
        """
        if not self.workflow_repository:
            raise BusinessLogicException(
                "Cannot delete workflow: no repository configured",
                rule="repository_required"
            )
        
        # Check for active executions
        if hasattr(self.workflow_repository, 'get_active_executions'):
            active_executions = await self.workflow_repository.get_active_executions(workflow_id)
            if active_executions:
                raise BusinessLogicException(
                    f"Cannot delete workflow with {len(active_executions)} active executions",
                    rule="no_delete_with_active_executions",
                    details={"active_executions": len(active_executions)}
                )
        
        # Delete workflow
        deleted = await self.workflow_repository.delete_workflow(workflow_id)
        
        if deleted:
            self.logger.info(
                "Workflow deleted",
                extra={"workflow_id": workflow_id}
            )
        else:
            self.logger.warning(
                "Workflow not found for deletion",
                extra={"workflow_id": workflow_id}
            )
        
        return deleted
    
    async def execute_workflow(
        self,
        workflow_id: str,
        input_data: Dict[str, Any],
        run_id: Optional[str] = None,
        execution_options: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        Execute a workflow with the provided input data.
        
        This is the main entry point for workflow execution. It coordinates
        the entire execution lifecycle from start to finish.
        
        Args:
            workflow_id: Workflow identifier  
            input_data: Input data for workflow execution
            run_id: Optional custom run identifier
            execution_options: Optional execution configuration
            
        Returns:
            Complete ExecutionResult with all node results
            
        Raises:
            ResourceNotFoundException: If workflow not found
            ValidationError: If input data is invalid
            ExecutionError: If execution fails
        """
        start_time = datetime.utcnow()
        run_id = run_id or str(uuid4())
        
        self.logger.info(
            "Starting workflow execution",
            extra={
                "workflow_id": workflow_id,
                "run_id": run_id,
                "input_keys": list(input_data.keys()),
                "has_options": execution_options is not None
            }
        )
        
        try:
            # 1. Load and validate workflow
            workflow = await self.get_workflow(workflow_id)
            
            # 2. Validate input data against workflow schema
            await self._validate_input_data(workflow, input_data)
            
            # 3. Create execution context with alias mapping
            alias_to_node_mapping = {}
            for node in workflow.nodes:
                if hasattr(node, 'alias') and node.alias:
                    alias_to_node_mapping[node.alias] = node.id
            
            context = create_execution_context(
                run_id=run_id,
                alias_to_node_mapping=alias_to_node_mapping
            )
            
            # 4. Create execution result
            execution_result = create_execution_result(
                run_id=run_id,
                workflow_id=workflow_id,
                started_at=start_time
            )
            execution_result.status = ExecutionStatus.RUNNING
            execution_result.context = context
            
            # 5. Execute workflow using execution service
            execution_result = await self.execution_service.execute_workflow(
                workflow=workflow,
                context=context,
                execution_result=execution_result,
                options=execution_options or {}
            )
            
            # 6. Process final results
            execution_result = await self._finalize_execution_result(
                execution_result,
                workflow,
                context
            )
            
            # 7. Persist execution result
            if self.workflow_repository:
                await self.workflow_repository.save_execution_result(execution_result)
            
            self.logger.info(
                "Workflow execution completed",
                extra={
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "status": execution_result.status.value,
                    "duration_seconds": execution_result.duration_seconds,
                    "success_rate": execution_result.success_rate,
                    "node_count": len(execution_result.node_results)
                }
            )
            
            return execution_result
            
        except Exception as e:
            # Handle execution failure
            self.logger.error(
                "Workflow execution failed",
                extra={
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "duration_seconds": (datetime.utcnow() - start_time).total_seconds()
                }
            )
            
            # Create failed execution result if not already created
            try:
                if 'execution_result' not in locals():
                    execution_result = create_execution_result(
                        run_id=run_id,
                        workflow_id=workflow_id,
                        started_at=start_time
                    )
                
                execution_result.mark_failed(
                    error=self._create_execution_error(e, workflow_id, run_id)
                )
                
                # Try to persist failed result
                if self.workflow_repository:
                    await self.workflow_repository.save_execution_result(execution_result)
                
                return execution_result
                
            except Exception as persist_error:
                self.logger.error(
                    "Failed to persist failed execution result",
                    extra={
                        "workflow_id": workflow_id,
                        "run_id": run_id,
                        "persist_error": str(persist_error)
                    }
                )
                
            # Re-raise original exception
            raise
    
    async def execute_workflow_from_definition(
        self,
        definition: Dict[str, Any],
        input_data: Dict[str, Any],
        run_id: Optional[str] = None,
        execution_options: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        Execute a workflow directly from definition without persisting it.
        
        This is useful for one-off executions or testing scenarios.
        
        Args:
            definition: Workflow definition dictionary
            input_data: Input data for execution
            run_id: Optional custom run identifier
            execution_options: Optional execution configuration
            
        Returns:
            Complete ExecutionResult
            
        Raises:
            ValidationError: If definition or input is invalid
            ExecutionError: If execution fails
        """
        start_time = datetime.utcnow()
        run_id = run_id or str(uuid4())
        
        self.logger.info(
            "Executing workflow from definition",
            extra={
                "run_id": run_id,
                "definition_keys": list(definition.keys()),
                "input_keys": list(input_data.keys())
            }
        )
        
        try:
            # 1. Parse and validate workflow definition
            workflow = await self.validation_service.parse_and_validate_workflow(
                definition=definition,
                name=definition.get('name', 'Ad-hoc Workflow'),
                description=definition.get('description'),
                workflow_id=definition.get('id', str(uuid4()))
            )
            
            # 2. Validate input data
            await self._validate_input_data(workflow, input_data)
            
            # 3. Create execution context with alias mapping
            alias_to_node_mapping = {}
            for node in workflow.nodes:
                if hasattr(node, 'alias') and node.alias:
                    alias_to_node_mapping[node.alias] = node.id
            
            context = create_execution_context(
                run_id=run_id,
                alias_to_node_mapping=alias_to_node_mapping
            )
            
            # Set workflow input data in context for domain layer
            context.input_data = input_data
            context.workflow_id = workflow.id
            
            # CRITICAL FIX: Also set workflow input in variables for template resolution
            # This ensures ${workflow.input.X} templates work correctly
            if input_data:
                for key, value in input_data.items():
                    context.set_variable(f"workflow.input.{key}", value)
            
            # 4. Create execution result
            execution_result = create_execution_result(
                run_id=run_id,
                workflow_id=workflow.id,
                started_at=start_time
            )
            execution_result.status = ExecutionStatus.RUNNING
            execution_result.context = context
            
            # 5. Execute workflow
            execution_result = await self.execution_service.execute_workflow(
                workflow=workflow,
                context=context,
                execution_result=execution_result,
                options=execution_options or {}
            )
            
            # 6. Finalize results
            execution_result = await self._finalize_execution_result(
                execution_result,
                workflow,
                context
            )
            
            self.logger.info(
                "Ad-hoc workflow execution completed",
                extra={
                    "workflow_id": workflow.id,
                    "run_id": run_id,
                    "status": execution_result.status.value,
                    "duration_seconds": execution_result.duration_seconds
                }
            )
            
            return execution_result
            
        except Exception as e:
            self.logger.error(
                "Ad-hoc workflow execution failed",
                extra={
                    "run_id": run_id,
                    "error": str(e),
                    "error_type": e.__class__.__name__
                }
            )
            raise
    
    async def get_execution_result(self, run_id: str) -> Optional[ExecutionResult]:
        """
        Retrieve execution result by run ID.
        
        Args:
            run_id: Execution run identifier
            
        Returns:
            ExecutionResult if found, None otherwise
        """
        if not self.workflow_repository:
            raise BusinessLogicException(
                "Cannot retrieve execution result: no repository configured",
                rule="repository_required"
            )
        
        return await self.workflow_repository.get_execution_result(run_id)
    
    async def list_workflow_executions(
        self,
        workflow_id: str,
        limit: int = 50,
        offset: int = 0,
        status_filter: Optional[ExecutionStatus] = None
    ) -> List[ExecutionResult]:
        """
        List executions for a specific workflow.
        
        Args:
            workflow_id: Workflow identifier
            limit: Maximum number of results to return
            offset: Number of results to skip
            status_filter: Optional status filter
            
        Returns:
            List of ExecutionResult objects
        """
        if not self.workflow_repository:
            raise BusinessLogicException(
                "Cannot list executions: no repository configured",
                rule="repository_required"
            )
        
        return await self.workflow_repository.list_executions(
            workflow_id=workflow_id,
            limit=limit,
            offset=offset,
            status_filter=status_filter
        )
    
    async def cancel_execution(self, run_id: str) -> bool:
        """
        Cancel a running workflow execution.
        
        Args:
            run_id: Execution run identifier
            
        Returns:
            True if execution was cancelled, False if not found or not cancellable
        """
        if not self.execution_service:
            raise BusinessLogicException(
                "Cannot cancel execution: no execution service configured",
                rule="execution_service_required"
            )
        
        success = await self.execution_service.cancel_execution(run_id)
        
        if success:
            self.logger.info(
                "Execution cancelled",
                extra={"run_id": run_id}
            )
        else:
            self.logger.warning(
                "Failed to cancel execution",
                extra={"run_id": run_id}
            )
        
        return success
    
    # Private helper methods
    
    async def _validate_input_data(
        self,
        workflow: Workflow,
        input_data: Dict[str, Any]
    ) -> None:
        """
        Validate input data against workflow input schema.
        
        Args:
            workflow: Workflow domain object
            input_data: Input data to validate
            
        Raises:
            ValidationError: If input data is invalid
        """
        if not workflow.input_schema:
            # No schema defined, accept any input
            return
        
        # Use validation service for schema validation
        await self.validation_service.validate_input_data(
            input_data,
            workflow.input_schema
        )
    
    async def _finalize_execution_result(
        self,
        execution_result: ExecutionResult,
        workflow: Workflow,
        context: ExecutionContext
    ) -> ExecutionResult:
        """
        Finalize execution result with computed values and output.
        
        Args:
            execution_result: Execution result to finalize
            workflow: Workflow that was executed
            context: Execution context
            
        Returns:
            Finalized ExecutionResult
        """
        # Extract final output based on workflow output schema
        final_output = await self._extract_final_output(workflow, context)
        execution_result.output = final_output
        
        # Update execution metrics
        execution_result.metrics.network_calls_count = sum(
            result.metrics.network_calls_count for result in execution_result.node_results
        )
        execution_result.metrics.retries_count = sum(
            result.metrics.retries_count for result in execution_result.node_results
        )
        
        return execution_result
    
    async def _extract_final_output(
        self,
        workflow: Workflow,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """
        Extract final workflow output based on output schema or end nodes.
        
        Args:
            workflow: Workflow that was executed
            context: Execution context with node results
            
        Returns:
            Final workflow output dictionary
        """
        if workflow.output_schema:
            # Extract output based on defined schema
            # This is a simplified implementation - could be more sophisticated
            output = {}
            for key, schema_def in workflow.output_schema.items():
                if 'source_node' in schema_def:
                    node_result = context.get_node_result(schema_def['source_node'])
                    if node_result:
                        if 'source_key' in schema_def:
                            output[key] = node_result.data.get(schema_def['source_key'])
                        else:
                            output[key] = node_result.output
            return output
        else:
            # Default: return outputs from all end nodes
            end_nodes = workflow.get_end_nodes()
            output = {}
            for end_node in end_nodes:
                node_result = context.get_node_result(end_node.id)
                if node_result:
                    output[end_node.id] = {
                        'output': node_result.output,
                        'data': node_result.data
                    }
            return output
    
    def _create_execution_error(
        self,
        exception: Exception,
        workflow_id: str,
        run_id: str
    ) -> 'ExecutionError':
        """
        Create ExecutionError from exception.
        
        Args:
            exception: Source exception
            workflow_id: Workflow identifier
            run_id: Run identifier
            
        Returns:
            ExecutionError domain object
        """
        from ..domain.models.execution import ExecutionError
        
        error_type = exception.__class__.__name__
        error_code = getattr(exception, 'code', 'UNKNOWN_ERROR')
        message = str(exception)
        
        return ExecutionError(
            error_type=error_type,
            error_code=error_code,
            message=message,
            details={
                'workflow_id': workflow_id,
                'run_id': run_id,
                'original_exception': error_type
            },
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
        # Network and temporary errors are usually retryable
        retryable_types = [
            'ConnectionError',
            'TimeoutError',
            'TemporaryFailure',
            'ServiceUnavailable'
        ]
        
        return exception.__class__.__name__ in retryable_types