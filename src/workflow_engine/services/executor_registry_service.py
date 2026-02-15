"""
Node Executor Registry Service for the AI Workflow Engine.

This service manages the centralized registry of node executors, providing
a clean interface for registering, discovering, and executing different
node types. It bridges the gap between the domain service layer and the
execution infrastructure.

Author: AI Workflow Engine Team
"""

from typing import Dict, List, Optional, Type

from ..core.node_executor import ExecutorRegistry, NodeExecutor
from ..domain.enums.node_types import NodeType
from ..domain.models import Node, ExecutionContext, NodeResult
from ..domain.exceptions.base import ExecutionError


class NodeExecutorRegistryService:
    """
    Service for managing node executor registration and execution.
    
    This service provides a clean domain-oriented interface over the
    core ExecutorRegistry, handling the translation between domain
    objects and the execution infrastructure.
    """
    
    def __init__(self):
        """Initialize the executor registry service."""
        from ..shared.utils.logging import get_logger
        self.logger = get_logger(__name__)
        self.registry = ExecutorRegistry()
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Initialize the registry with all available executors.
        
        This method discovers and registers all node executor implementations
        following a convention-based approach.
        """
        if self._initialized:
            return
        
        self.logger.info("Initializing node executor registry")
        
        try:
            # Register all available executors
            await self._register_built_in_executors()
            
            self._initialized = True
            
            self.logger.info(
                "Node executor registry initialized successfully",
                registered_types=list(self.registry.list_executors().keys()),
                executor_count=len(self.registry.list_executors())
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to initialize node executor registry",
                error=str(e),
                error_type=e.__class__.__name__
            )
            raise ExecutionError(
                message="Failed to initialize node executor registry",
                details={"error": str(e)}
            )
    
    async def _register_built_in_executors(self) -> None:
        """Register all built-in node executors."""
        # Import executors dynamically to avoid circular imports
        from ..executors.start_executor import StartExecutor
        from ..executors.end_executor import EndExecutor
        from ..executors.agent_executor import AgentExecutor
        from ..executors.mcp_executor import MCPToolExecutor
        from ..executors.condition_executor import ConditionExecutor
        
        # Register each executor with its node type
        executors_to_register = [
            (NodeType.START.value, StartExecutor()),
            (NodeType.END.value, EndExecutor()),
            (NodeType.AGENT.value, AgentExecutor()),
            (NodeType.MCP_TOOL.value, MCPToolExecutor()),
            (NodeType.CONDITION.value, ConditionExecutor()),
        ]
        
        for node_type, executor_instance in executors_to_register:
            try:
                self.registry.register(node_type, executor_instance)
                self.logger.debug(
                    "Registered executor",
                    node_type=node_type,
                    executor_class=executor_instance.__class__.__name__
                )
            except Exception as e:
                self.logger.error(
                    "Failed to register executor",
                    node_type=node_type,
                    executor_class=executor_instance.__class__.__name__,
                    error=str(e)
                )
                # Continue registering other executors even if one fails
                continue
    
    def get_executor(self, node_type: NodeType) -> Optional[NodeExecutor]:
        """
        Get executor for a specific node type.
        
        Args:
            node_type: Domain NodeType enum
            
        Returns:
            NodeExecutor instance or None if not found
        """
        return self.registry.get_executor(node_type.value)
    
    def is_supported(self, node_type: NodeType) -> bool:
        """
        Check if a node type is supported.
        
        Args:
            node_type: Domain NodeType enum
            
        Returns:
            True if supported, False otherwise
        """
        return self.registry.is_supported(node_type.value)
    
    def list_supported_types(self) -> List[NodeType]:
        """
        Get list of all supported node types.
        
        Returns:
            List of supported NodeType enums
        """
        supported_strings = list(self.registry.list_executors().keys())
        supported_types = []
        
        for type_str in supported_strings:
            try:
                node_type = NodeType(type_str)
                supported_types.append(node_type)
            except ValueError:
                # Log unknown node type but continue
                self.logger.warning(
                    "Unknown node type in registry",
                    node_type=type_str
                )
                continue
        
        return supported_types
    
    def get_executor_info(self) -> Dict[str, Dict[str, any]]:
        """
        Get information about all registered executors.
        
        Returns:
            Dictionary mapping node types to executor information
        """
        info = {}
        
        for node_type_str, executor_class_name in self.registry.list_executors().items():
            executor = self.registry.get_executor(node_type_str)
            if executor:
                info[node_type_str] = {
                    "executor_class": executor_class_name,
                    "node_type": node_type_str,
                    "default_timeout": getattr(executor, 'default_timeout', None),
                    "supports_retry": True,
                    "supports_timeout": True,
                    "executor_info": executor.get_node_info()
                }
        
        return info
    
    async def execute_node(
        self,
        node: Node,
        context: ExecutionContext
    ) -> NodeResult:
        """
        Execute a domain Node using the appropriate executor.
        
        This method bridges between domain objects and the core execution
        infrastructure, handling the translation between domain and core models.
        
        Args:
            node: Domain Node object to execute
            context: Domain ExecutionContext
            
        Returns:
            Domain NodeResult object
            
        Raises:
            ExecutionError: If execution fails or no executor is found
        """
        if not self._initialized:
            await self.initialize()
        
        self.logger.info(
            "Executing node via registry service", 
            node_id=node.id,
            node_type=node.type.value
        )
        
        # Get executor for node type
        executor = self.get_executor(node.type)
        if not executor:
            available_types = [t.value for t in self.list_supported_types()]
            raise ExecutionError(
                message=f"No executor registered for node type: {node.type.value}",
                details={
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "available_types": available_types
                }
            )
        
        try:
            # Convert domain Node to core WorkflowNode for executor
            core_node = self._convert_domain_node_to_core(node)
            
            # Convert domain ExecutionContext to core context  
            core_context = self._convert_domain_context_to_core(context)
            
            # Execute using core executor
            core_result = await executor.execute(core_node, core_context)
            
            # Apply context updates back to domain context for next nodes
            if hasattr(core_result, 'context_updates') and core_result.context_updates:
                self.logger.info(
                    "Processing context updates",
                    node_id=node.id,
                    total_updates=len(core_result.context_updates),
                    update_keys=list(core_result.context_updates.keys())
                )
                
                for key, value in core_result.context_updates.items():
                    # Store all context updates including complex types (dict, list)
                    # so downstream nodes can access MCP/tool outputs via template resolution.
                    # Skip only .full metadata keys to reduce context size.
                    if not key.endswith('.full'):
                        context.set_variable(key, value)
                        self.logger.info(
                            "Applied context update",
                            node_id=node.id,
                            key=key,
                            value_type=type(value).__name__,
                            value_preview=str(value)[:200] if value is not None else None
                        )
                    else:
                        self.logger.debug(
                            "Skipped .full metadata context update",
                            node_id=node.id,
                            key=key,
                            value_type=type(value).__name__
                        )
            
            # Convert core ExecutionResult to domain NodeResult
            domain_result = self._convert_core_result_to_domain(
                core_result, 
                node, 
                context
            )
            
            self.logger.info(
                "Node execution completed via registry service",
                node_id=node.id,
                status=domain_result.status.value,
                duration_seconds=domain_result.duration_seconds
            )
            
            return domain_result
            
        except Exception as e:
            self.logger.error(
                "Node execution failed via registry service",
                node_id=node.id,
                node_type=node.type.value,
                error=str(e),
                error_type=e.__class__.__name__
            )
            
            # Create failed NodeResult for domain layer
            from ..domain.models.execution import NodeResult, ExecutionError as DomainExecutionError
            from ..domain.enums.execution_status import NodeExecutionStatus
            from datetime import datetime
            
            failed_result = NodeResult(
                node_id=node.id,
                node_type=node.type,
                status=NodeExecutionStatus.FAILED,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                error=DomainExecutionError(
                    error_type=e.__class__.__name__,
                    error_code="EXECUTION_FAILED",
                    message=str(e),
                    node_id=node.id
                )
            )
            
            return failed_result
    
    def _convert_domain_node_to_core(self, domain_node: Node) -> 'WorkflowNode':
        """
        Convert domain Node to core WorkflowNode.
        
        Args:
            domain_node: Domain Node object
            
        Returns:
            Core WorkflowNode object for executor consumption
        """
        from ..core.schemas import WorkflowNode
        
        # Convert domain Node to core WorkflowNode format
        return WorkflowNode(
            id=domain_node.id,
            type=domain_node.type.value,
            config=domain_node.config,
            name=domain_node.name,
            description=domain_node.description,
            next=domain_node.depends_on  # Note: this mapping may need adjustment based on actual schema
        )
    
    def _convert_domain_context_to_core(self, domain_context: ExecutionContext) -> 'ExecutionContext':
        """
        Convert domain ExecutionContext to core ExecutionContext.
        
        For now, this is a pass-through since both contexts have similar structure.
        In the future, this could handle more complex mappings.
        
        Args:
            domain_context: Domain ExecutionContext
            
        Returns:
            Core ExecutionContext for executor consumption
        """
        # TODO: Implement proper context conversion when core context is different
        # For now, create a core context from the domain context data
        from ..core.context import ExecutionContext as CoreExecutionContext
        
        # Create core context - this is a simplified implementation
        # In a full implementation, this would properly map all context data
        core_context = CoreExecutionContext(
            run_id=domain_context.run_id,
            alias_to_node_mapping=domain_context.alias_to_node_mapping
        )
        
        # Copy over workflow and input data
        # CRITICAL FIX: Set workflow input data properly in core context namespace
        if hasattr(domain_context, 'input_data') and domain_context.input_data:
            # Set the entire input_data object
            core_context._namespace.set("workflow.input", domain_context.input_data)
            
            # ALSO set individual fields for ${workflow.input.X} template resolution
            for key, value in domain_context.input_data.items():
                core_context._namespace.set(f"workflow.input.{key}", value)
        
        # Copy all domain context variables to core context
        if hasattr(domain_context, 'variables') and domain_context.variables:
            for key, value in domain_context.variables.items():
                core_context._namespace.set(key, value)
        
        return core_context
    
    def _convert_core_result_to_domain(
        self,
        core_result,
        domain_node: Node,
        domain_context: ExecutionContext
    ) -> NodeResult:
        """
        Convert core ExecutionResult to domain NodeResult.
        
        Args:
            core_result: Core ExecutionResult from executor
            domain_node: Original domain Node object
            domain_context: Domain ExecutionContext
            
        Returns:
            Domain NodeResult object
        """
        from ..domain.models.execution import (
            NodeResult, 
            ExecutionError as DomainExecutionError,
            ExecutionMetrics
        )
        from ..domain.enums.execution_status import NodeExecutionStatus
        from datetime import datetime
        
        # Map core status to domain status
        status_mapping = {
            "pending": NodeExecutionStatus.PENDING,
            "running": NodeExecutionStatus.RUNNING,
            "success": NodeExecutionStatus.SUCCESS,
            "failed": NodeExecutionStatus.FAILED,
            "timeout": NodeExecutionStatus.TIMEOUT,
            "cancelled": NodeExecutionStatus.FAILED,  # Map cancelled to failed
            "retrying": NodeExecutionStatus.RUNNING,  # Map retrying to running
            "skipped": NodeExecutionStatus.SKIPPED,
        }
        
        domain_status = status_mapping.get(
            core_result.status.value.lower(), 
            NodeExecutionStatus.FAILED
        )
        
        # Create domain NodeResult
        domain_result = NodeResult(
            node_id=domain_node.id,
            node_type=domain_node.type,
            status=domain_status,
            started_at=datetime.utcnow(),  # TODO: Get actual start time from core result
            data=core_result.data or {},
            output=core_result.data.get('output') if core_result.data else None,
            attempts=core_result.retry_count + 1
        )
        
        # Set finish time if execution is complete
        if domain_status.is_terminal:
            domain_result.finished_at = datetime.utcnow()  # TODO: Get actual end time
        
        # Convert error if present
        if core_result.error:
            domain_result.error = DomainExecutionError(
                error_type=core_result.error.get('type', 'Unknown'),
                error_code='EXECUTION_ERROR',
                message=core_result.error.get('message', 'Unknown error'),
                node_id=domain_node.id,
                details=core_result.error
            )
        
        # Convert metrics if present
        if core_result.metrics:
            domain_result.metrics = ExecutionMetrics(
                total_duration_seconds=core_result.metrics.duration_ms / 1000 if core_result.metrics.duration_ms else None,
                execution_time_seconds=core_result.metrics.duration_ms / 1000 if core_result.metrics.duration_ms else None,
                memory_usage_mb=core_result.metrics.memory_usage_mb,
                network_calls_count=core_result.metrics.network_calls,
                retries_count=core_result.retry_count
            )
        
        return domain_result
    
    async def health_check(self) -> Dict[str, any]:
        """
        Perform health check on the executor registry.
        
        Returns:
            Dictionary with health status information
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            supported_types = self.list_supported_types()
            executor_info = self.get_executor_info()
            
            return {
                "status": "healthy",
                "initialized": self._initialized,
                "supported_node_types": [t.value for t in supported_types],
                "executor_count": len(executor_info),
                "executors": executor_info
            }
            
        except Exception as e:
            self.logger.error(f"Health check failed - Error: {str(e)}")
            return {
                "status": "unhealthy",
                "initialized": self._initialized,
                "error": str(e),
                "supported_node_types": [],
                "executor_count": 0,
                "executors": {}
            }