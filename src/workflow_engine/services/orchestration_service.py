"""
High-level Workflow Orchestration Service for the AI Workflow Engine.

This service provides a simplified, high-level interface for workflow
operations, orchestrating between all the domain services and handling
cross-cutting concerns like logging, metrics, and error coordination.

Author: AI Workflow Engine Team
"""

import logging
from typing import Dict, List, Optional, Any
from uuid import uuid4
from datetime import datetime

from ..domain.models import Workflow, ExecutionResult
from ..domain.enums.execution_status import ExecutionStatus
from ..domain.exceptions.base import (
    ValidationError,
    ExecutionError,
    BusinessLogicException,
    ResourceNotFoundException,
)
from .workflow_service import WorkflowService
from .execution_service import ExecutionService
from .validation_service import ValidationService
from .response_service import ResponseService
from .executor_registry_service import NodeExecutorRegistryService


class WorkflowOrchestrationService:
    """
    High-level orchestration service that coordinates all workflow operations.
    
    This service provides a simplified interface for the application layer,
    handling the coordination between domain services and cross-cutting concerns
    like logging, metrics collection, and error handling.
    """
    
    def __init__(
        self,
        workflow_service: WorkflowService,
        execution_service: ExecutionService,
        validation_service: ValidationService,
        response_service: ResponseService,
        executor_registry_service: NodeExecutorRegistryService
    ):
        """
        Initialize the orchestration service.
        
        Args:
            workflow_service: WorkflowService for workflow management
            execution_service: ExecutionService for execution coordination
            validation_service: ValidationService for validation logic
            response_service: ResponseService for response transformation
            executor_registry_service: NodeExecutorRegistryService for executor management
        """
        self.workflow_service = workflow_service
        self.execution_service = execution_service
        self.validation_service = validation_service
        self.response_service = response_service
        self.executor_registry_service = executor_registry_service
        self.logger = logging.getLogger(__name__)
        
        # Metrics and monitoring
        self._execution_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._total_execution_time = 0.0
    
    async def execute_workflow_definition(
        self,
        definition: Dict[str, Any],
        input_data: Dict[str, Any],
        run_id: Optional[str] = None,
        execution_options: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> ExecutionResult:
        """
        Execute a workflow definition end-to-end with full orchestration.
        
        This is the main entry point for workflow execution, providing:
        - Complete validation and error handling
        - Execution coordination and monitoring
        - Metrics collection and logging
        - Result processing and transformation
        
        Args:
            definition: Workflow definition dictionary
            input_data: Input data for workflow execution
            run_id: Optional custom run identifier
            execution_options: Optional execution configuration
            correlation_id: Optional correlation ID for tracing
            
        Returns:
            Complete ExecutionResult with all processing applied
            
        Raises:
            ValidationError: If definition or input is invalid
            ExecutionError: If execution fails
        """
        run_id = run_id or str(uuid4())
        start_time = datetime.utcnow()
        
        self.logger.info(
            "Starting orchestrated workflow execution",
            workflow_name=definition.get('name', 'unknown'),
            run_id=run_id,
            correlation_id=correlation_id,
            has_options=execution_options is not None
        )
        
        try:
            # Update execution metrics
            self._execution_count += 1
            
            # Execute using workflow service
            execution_result = await self.workflow_service.execute_workflow_from_definition(
                definition=definition,
                input_data=input_data,
                run_id=run_id,
                execution_options=execution_options
            )
            
            # Update success/failure metrics
            if execution_result.is_successful:
                self._success_count += 1
            else:
                self._failure_count += 1
            
            # Track execution time
            if execution_result.duration_seconds:
                self._total_execution_time += execution_result.duration_seconds
            
            self.logger.info(
                "Orchestrated workflow execution completed",
                run_id=run_id,
                status=execution_result.status.value,
                success_rate=execution_result.success_rate,
                duration_seconds=execution_result.duration_seconds,
                node_count=len(execution_result.node_results)
            )
            
            return execution_result
            
        except Exception as e:
            self._failure_count += 1
            
            self.logger.error(
                "Orchestrated workflow execution failed",
                run_id=run_id,
                error=str(e),
                error_type=e.__class__.__name__,
                correlation_id=correlation_id
            )
            raise
    
    async def validate_workflow_definition(
        self,
        definition: Dict[str, Any],
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate a workflow definition with comprehensive feedback.
        
        Args:
            definition: Workflow definition to validate
            name: Optional workflow name override
            description: Optional workflow description override
            
        Returns:
            Validation results with detailed feedback
            
        Raises:
            ValidationError: If validation fails
        """
        self.logger.info(
            "Starting workflow definition validation",
            workflow_name=name or definition.get('name', 'unknown')
        )
        
        try:
            # Create workflow (this validates it comprehensively)
            workflow = await self.validation_service.parse_and_validate_workflow(
                definition=definition,
                name=name,
                description=description
            )
            
            # Get executor support information
            executor_info = self.executor_registry_service.get_executor_info()
            supported_types = [t.value for t in self.executor_registry_service.list_supported_types()]
            
            # Check node type support
            unsupported_types = []
            for node in workflow.nodes:
                if node.type.value not in supported_types:
                    unsupported_types.append(node.type.value)
            
            validation_results = {
                "is_valid": True,
                "workflow_id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "node_count": workflow.node_count,
                "connection_count": workflow.connection_count,
                "structure_valid": workflow.is_valid,
                "supported_node_types": supported_types,
                "unsupported_node_types": list(set(unsupported_types)),
                "executor_info": executor_info,
                "validation_timestamp": datetime.utcnow().isoformat()
            }
            
            # Add warnings for unsupported types
            if unsupported_types:
                validation_results["warnings"] = [
                    f"Unsupported node types found: {unsupported_types}. "
                    f"These nodes may fail during execution."
                ]
            
            self.logger.info(
                "Workflow definition validation completed successfully",
                workflow_id=workflow.id,
                node_count=workflow.node_count,
                unsupported_types=len(unsupported_types)
            )
            
            return validation_results
            
        except ValidationError as e:
            self.logger.warning(
                "Workflow definition validation failed",
                error=e.message,
                details=e.details
            )
            raise
    
    async def get_execution_status(self, run_id: str) -> Optional[ExecutionResult]:
        """
        Get the current status of a workflow execution.
        
        Args:
            run_id: Execution run identifier
            
        Returns:
            ExecutionResult if found, None otherwise
        """
        self.logger.debug(f"Retrieving execution status - run_id: {run_id}")
        
        try:
            return await self.workflow_service.get_execution_result(run_id)
        except Exception as e:
            self.logger.error(
                f"Failed to retrieve execution status - run_id: {run_id}, error: {str(e)}"
            )
            return None
    
    async def list_recent_executions(
        self,
        limit: int = 50,
        workflow_id: Optional[str] = None,
        status_filter: Optional[ExecutionStatus] = None
    ) -> List[ExecutionResult]:
        """
        List recent workflow executions with filtering.
        
        Args:
            limit: Maximum number of results to return
            workflow_id: Optional workflow ID filter
            status_filter: Optional status filter
            
        Returns:
            List of recent ExecutionResult objects
        """
        self.logger.debug(
            f"Listing recent executions - limit: {limit}, workflow_id: {workflow_id}, status_filter: {status_filter.value if status_filter else None}"
        )
        
        try:
            if workflow_id:
                return await self.workflow_service.list_workflow_executions(
                    workflow_id=workflow_id,
                    limit=limit,
                    status_filter=status_filter
                )
            else:
                # TODO: Implement global execution listing when repository supports it
                return []
        except Exception as e:
            self.logger.error(
                "Failed to list executions",
                error=str(e)
            )
            return []
    
    async def cancel_execution(self, run_id: str) -> bool:
        """
        Cancel a running workflow execution.
        
        Args:
            run_id: Execution run identifier
            
        Returns:
            True if execution was cancelled, False otherwise
        """
        self.logger.info(f"Cancelling workflow execution - run_id: {run_id}")
        
        try:
            return await self.execution_service.cancel_execution(run_id)
        except Exception as e:
            self.logger.error(
                f"Failed to cancel execution - run_id: {run_id}, error: {str(e)}"
            )
            return False
    
    async def get_system_health(self) -> Dict[str, Any]:
        """
        Get comprehensive system health information.
        
        Returns:
            Dictionary with system health and status information
        """
        self.logger.debug("Performing system health check")
        
        try:
            # Get executor registry health
            executor_health = await self.executor_registry_service.health_check()
            
            # Calculate execution metrics
            success_rate = (
                self._success_count / self._execution_count 
                if self._execution_count > 0 else 0.0
            )
            
            avg_execution_time = (
                self._total_execution_time / self._execution_count
                if self._execution_count > 0 else 0.0
            )
            
            health_data = {
                "status": "healthy" if executor_health.get("status") == "healthy" else "degraded",
                "timestamp": datetime.utcnow().isoformat(),
                "execution_metrics": {
                    "total_executions": self._execution_count,
                    "successful_executions": self._success_count,
                    "failed_executions": self._failure_count,
                    "success_rate": success_rate,
                    "avg_execution_time_seconds": avg_execution_time
                },
                "executor_registry": executor_health,
                "services": {
                    "workflow_service": "healthy",
                    "execution_service": "healthy", 
                    "validation_service": "healthy",
                    "response_service": "healthy"
                }
            }
            
            self.logger.info(
                "System health check completed",
                status=health_data["status"],
                total_executions=self._execution_count,
                success_rate=success_rate
            )
            
            return health_data
            
        except Exception as e:
            self.logger.error(
                "System health check failed",
                error=str(e)
            )
            
            return {
                "status": "unhealthy",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "execution_metrics": {
                    "total_executions": self._execution_count,
                    "successful_executions": self._success_count,
                    "failed_executions": self._failure_count,
                    "success_rate": 0.0,
                    "avg_execution_time_seconds": 0.0
                }
            }
    
    async def get_supported_capabilities(self) -> Dict[str, Any]:
        """
        Get information about supported workflow capabilities.
        
        Returns:
            Dictionary with supported features and node types
        """
        try:
            supported_types = self.executor_registry_service.list_supported_types()
            executor_info = self.executor_registry_service.get_executor_info()
            
            return {
                "supported_node_types": [t.value for t in supported_types],
                "node_type_count": len(supported_types),
                "executors": executor_info,
                "features": {
                    "parallel_execution": True,
                    "conditional_logic": True,
                    "retry_logic": True,
                    "timeout_handling": True,
                    "error_recovery": True,
                    "context_sharing": True,
                    "dag_validation": True,
                    "metrics_collection": True
                },
                "limits": {
                    "max_parallel_nodes": self.execution_service.max_parallel_nodes,
                    "default_timeout_seconds": self.execution_service.default_timeout_seconds
                }
            }
            
        except Exception as e:
            self.logger.error(
                "Failed to get supported capabilities",
                error=str(e)
            )
            return {
                "supported_node_types": [],
                "node_type_count": 0,
                "executors": {},
                "features": {},
                "limits": {}
            }
    
    def reset_metrics(self) -> None:
        """Reset execution metrics (useful for testing)."""
        self._execution_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._total_execution_time = 0.0
        self.logger.info("Execution metrics reset")