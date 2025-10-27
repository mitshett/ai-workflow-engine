"""
Execution domain models for the AI Workflow Engine.

This module contains domain models related to workflow execution,
including execution results, node results, and execution context.

Author: AI Workflow Engine Team
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from ..enums.execution_status import ExecutionStatus, NodeExecutionStatus
from ..enums.node_types import NodeType
from ..exceptions.base import ValidationError


@dataclass
class ExecutionMetrics:
    """
    Metrics and performance data for workflow executions.
    
    Captures timing, resource usage, and other performance indicators
    for analysis and optimization purposes.
    """
    
    total_duration_seconds: Optional[float] = None
    queue_time_seconds: Optional[float] = None
    execution_time_seconds: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    cpu_usage_percent: Optional[float] = None
    network_calls_count: int = 0
    retries_count: int = 0
    
    @property
    def efficiency_score(self) -> float:
        """Calculate an efficiency score (0.0 to 1.0) based on metrics."""
        if not self.total_duration_seconds or not self.execution_time_seconds:
            return 0.0
        
        # Efficiency is execution time / total time (higher is better)
        efficiency = self.execution_time_seconds / self.total_duration_seconds
        return min(1.0, max(0.0, efficiency))
    
    @property
    def had_retries(self) -> bool:
        """Check if execution required retries."""
        return self.retries_count > 0


@dataclass
class ExecutionError:
    """
    Detailed error information for failed executions.
    
    Provides structured error data to aid in debugging and
    automated error handling.
    """
    
    error_type: str
    error_code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    node_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_retryable: bool = False
    
    def __post_init__(self):
        """Validate error data after initialization."""
        if not self.error_type or not self.error_type.strip():
            raise ValidationError("Error type cannot be empty")
        if not self.error_code or not self.error_code.strip():
            raise ValidationError("Error code cannot be empty")
        if not self.message or not self.message.strip():
            raise ValidationError("Error message cannot be empty")
    
    @property
    def is_user_error(self) -> bool:
        """Check if this is a user configuration error."""
        user_error_codes = ['INVALID_CONFIG', 'MISSING_PARAMETER', 'VALIDATION_ERROR']
        return self.error_code in user_error_codes
    
    @property
    def is_system_error(self) -> bool:
        """Check if this is a system/infrastructure error."""
        system_error_codes = ['NETWORK_ERROR', 'DATABASE_ERROR', 'TIMEOUT', 'RESOURCE_EXHAUSTED']
        return self.error_code in system_error_codes
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary representation."""
        return {
            'error_type': self.error_type,
            'error_code': self.error_code,
            'message': self.message,
            'details': self.details,
            'stack_trace': self.stack_trace,
            'node_id': self.node_id,
            'timestamp': self.timestamp.isoformat(),
            'is_retryable': self.is_retryable,
            'is_user_error': self.is_user_error,
            'is_system_error': self.is_system_error
        }


@dataclass
class NodeResult:
    """
    Result of executing a single node in the workflow.
    
    Contains the output data, status, timing information,
    and any errors that occurred during node execution.
    """
    
    node_id: str
    node_type: NodeType
    status: NodeExecutionStatus
    started_at: datetime
    finished_at: Optional[datetime] = None
    data: Dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: Optional[ExecutionError] = None
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    attempts: int = 1
    
    def __post_init__(self):
        """Validate node result data after initialization."""
        if not self.node_id or not self.node_id.strip():
            raise ValidationError("Node ID cannot be empty")
        
        if not isinstance(self.node_type, NodeType):
            raise ValidationError(f"Invalid node type: {self.node_type}")
        
        if not isinstance(self.status, NodeExecutionStatus):
            raise ValidationError(f"Invalid node execution status: {self.status}")
        
        # Calculate metrics if finished
        if self.finished_at and self.started_at:
            duration = (self.finished_at - self.started_at).total_seconds()
            self.metrics.total_duration_seconds = duration
            self.metrics.execution_time_seconds = duration
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate the execution duration in seconds."""
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
    
    @property
    def duration_timedelta(self) -> Optional[timedelta]:
        """Get the execution duration as a timedelta object."""
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return None
    
    @property
    def is_completed(self) -> bool:
        """Check if the node execution is complete."""
        return self.status.is_terminal
    
    @property
    def is_successful(self) -> bool:
        """Check if the node execution was successful."""
        return self.status.is_successful
    
    @property
    def is_failed(self) -> bool:
        """Check if the node execution failed."""
        return self.status.is_error
    
    @property
    def is_running(self) -> bool:
        """Check if the node is currently running."""
        return self.status == NodeExecutionStatus.RUNNING
    
    @property
    def has_output(self) -> bool:
        """Check if the node produced output data."""
        return self.output is not None or bool(self.data)
    
    def mark_completed(self, output: Any = None, data: Dict[str, Any] = None) -> None:
        """Mark the node execution as successfully completed."""
        self.status = NodeExecutionStatus.SUCCESS
        self.finished_at = datetime.utcnow()
        if output is not None:
            self.output = output
        if data:
            self.data.update(data)
        
        # Update metrics
        if self.started_at:
            duration = (self.finished_at - self.started_at).total_seconds()
            self.metrics.total_duration_seconds = duration
            self.metrics.execution_time_seconds = duration
    
    def mark_failed(self, error: ExecutionError) -> None:
        """Mark the node execution as failed with error details."""
        self.status = NodeExecutionStatus.FAILED
        self.finished_at = datetime.utcnow()
        self.error = error
        
        # Update metrics
        if self.started_at:
            duration = (self.finished_at - self.started_at).total_seconds()
            self.metrics.total_duration_seconds = duration
    
    def mark_timeout(self) -> None:
        """Mark the node execution as timed out."""
        self.status = NodeExecutionStatus.TIMEOUT
        self.finished_at = datetime.utcnow()
        self.error = ExecutionError(
            error_type="TimeoutError",
            error_code="EXECUTION_TIMEOUT",
            message=f"Node {self.node_id} execution timed out",
            node_id=self.node_id,
            is_retryable=True
        )
    
    def increment_attempts(self) -> None:
        """Increment the attempt counter for retries."""
        self.attempts += 1
        self.metrics.retries_count = self.attempts - 1
    
    def get_simple_output(self) -> str:
        """Get a simplified string representation of the output."""
        if self.output is not None:
            if isinstance(self.output, str):
                return self.output[:200] + "..." if len(self.output) > 200 else self.output
            else:
                return str(self.output)[:200] + "..."
        
        if self.data:
            # Try to extract a meaningful response from data
            for key in ['response', 'result', 'output', 'message']:
                if key in self.data:
                    value = str(self.data[key])
                    return value[:200] + "..." if len(value) > 200 else value
        
        return f"{self.node_type.value} node executed successfully"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert node result to dictionary representation."""
        result_dict = {
            'node_id': self.node_id,
            'node_type': self.node_type.value,
            'status': self.status.value,
            'started_at': self.started_at.isoformat(),
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'duration_seconds': self.duration_seconds,
            'data': self.data,
            'output': self.output,
            'attempts': self.attempts,
            'has_output': self.has_output,
            'is_successful': self.is_successful,
            'is_failed': self.is_failed,
            'simple_output': self.get_simple_output()
        }
        
        if self.error:
            result_dict['error'] = self.error.to_dict()
        
        return result_dict


@dataclass
class ExecutionContext:
    """
    Execution context that maintains state during workflow execution.
    
    Provides access to workflow input, node results, and shared state
    that nodes can read from and write to during execution.
    """
    
    run_id: str
    workflow_id: str = ""  # No longer required since we removed DB persistence
    input_data: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    node_results: Dict[str, NodeResult] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    alias_to_node_mapping: Optional[Dict[str, str]] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate context data after initialization."""
        if not self.run_id or not self.run_id.strip():
            raise ValidationError("Run ID cannot be empty")
    
    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get a variable from the execution context."""
        return self.variables.get(key, default)
    
    def set_variable(self, key: str, value: Any) -> None:
        """Set a variable in the execution context."""
        self.variables[key] = value
    
    def get_node_result(self, node_id: str) -> Optional[NodeResult]:
        """Get the result of a specific node execution."""
        return self.node_results.get(node_id)
    
    def get_node_output(self, node_id: str) -> Any:
        """Get the output of a specific node execution."""
        result = self.get_node_result(node_id)
        return result.output if result else None
    
    def get_node_data(self, node_id: str, key: str = None) -> Any:
        """Get data from a specific node execution."""
        result = self.get_node_result(node_id)
        if not result:
            return None
        
        if key is None:
            return result.data
        
        return result.data.get(key)
    
    def add_node_result(self, result: NodeResult) -> None:
        """Add a node execution result to the context."""
        self.node_results[result.node_id] = result
    
    def get_successful_nodes(self) -> List[str]:
        """Get IDs of all successfully executed nodes."""
        return [
            node_id for node_id, result in self.node_results.items()
            if result.is_successful
        ]
    
    def get_failed_nodes(self) -> List[str]:
        """Get IDs of all failed nodes."""
        return [
            node_id for node_id, result in self.node_results.items()
            if result.is_failed
        ]
    
    def get_completed_nodes(self) -> List[str]:
        """Get IDs of all completed nodes (successful or failed)."""
        return [
            node_id for node_id, result in self.node_results.items()
            if result.is_completed
        ]
    
    def is_node_completed(self, node_id: str) -> bool:
        """Check if a specific node has completed execution."""
        result = self.get_node_result(node_id)
        return result.is_completed if result else False
    
    def is_node_successful(self, node_id: str) -> bool:
        """Check if a specific node executed successfully."""
        result = self.get_node_result(node_id)
        return result.is_successful if result else False
    
    def get_context_for_node(self, node_id: str) -> Dict[str, Any]:
        """Get a context dictionary for template resolution in a node."""
        return {
            'workflow': {
                'id': self.workflow_id,
                'input': self.input_data,
                'run_id': self.run_id
            },
            'variables': self.variables,
            'nodes': {
                result_node_id: {
                    'output': result.output,
                    'data': result.data,
                    'status': result.status.value,
                    'simple_output': result.get_simple_output()
                }
                for result_node_id, result in self.node_results.items()
            },
            'current': {
                'node_id': node_id,
                'timestamp': datetime.utcnow().isoformat(),
                'run_id': self.run_id
            }
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert execution context to dictionary representation."""
        return {
            'run_id': self.run_id,
            'workflow_id': self.workflow_id,
            'input_data': self.input_data,
            'variables': self.variables,
            'created_at': self.created_at.isoformat(),
            'node_results': {
                node_id: result.to_dict()
                for node_id, result in self.node_results.items()
            },
            'successful_nodes': self.get_successful_nodes(),
            'failed_nodes': self.get_failed_nodes(),
            'completed_nodes': self.get_completed_nodes()
        }


@dataclass
class ExecutionResult:
    """
    Complete result of a workflow execution.
    
    This is the aggregate result containing all node results,
    final status, timing information, and execution metadata.
    """
    
    run_id: str
    workflow_id: str
    status: ExecutionStatus
    started_at: datetime
    finished_at: Optional[datetime] = None
    node_results: List[NodeResult] = field(default_factory=list)
    context: Optional[ExecutionContext] = None
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[ExecutionError] = None
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    
    def __post_init__(self):
        """Validate execution result data after initialization."""
        if not self.run_id or not self.run_id.strip():
            raise ValidationError("Run ID cannot be empty")
        if not self.workflow_id or not self.workflow_id.strip():
            raise ValidationError("Workflow ID cannot be empty")
        if not isinstance(self.status, ExecutionStatus):
            raise ValidationError(f"Invalid execution status: {self.status}")
        
        # Calculate metrics if execution is finished
        if self.finished_at and self.started_at:
            duration = (self.finished_at - self.started_at).total_seconds()
            self.metrics.total_duration_seconds = duration
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate the total execution duration in seconds."""
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
    
    @property
    def duration_timedelta(self) -> Optional[timedelta]:
        """Get the execution duration as a timedelta object."""
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return None
    
    @property
    def is_completed(self) -> bool:
        """Check if the workflow execution is complete."""
        return self.status.is_terminal
    
    @property
    def is_successful(self) -> bool:
        """Check if the workflow execution was successful."""
        return self.status.is_successful
    
    @property
    def is_failed(self) -> bool:
        """Check if the workflow execution failed."""
        return self.status.is_error
    
    @property
    def is_running(self) -> bool:
        """Check if the workflow is currently running."""
        return self.status == ExecutionStatus.RUNNING
    
    @property
    def success_rate(self) -> float:
        """Calculate the success rate of node executions (0.0 to 1.0)."""
        if not self.node_results:
            return 0.0
        
        successful_count = sum(1 for result in self.node_results if result.is_successful)
        return successful_count / len(self.node_results)
    
    @property
    def total_retries(self) -> int:
        """Get the total number of retries across all nodes."""
        return sum(result.metrics.retries_count for result in self.node_results)
    
    def get_node_result(self, node_id: str) -> Optional[NodeResult]:
        """Get the result for a specific node."""
        return next((result for result in self.node_results if result.node_id == node_id), None)
    
    def get_successful_nodes(self) -> List[NodeResult]:
        """Get all successfully executed node results."""
        return [result for result in self.node_results if result.is_successful]
    
    def get_failed_nodes(self) -> List[NodeResult]:
        """Get all failed node results."""
        return [result for result in self.node_results if result.is_failed]
    
    def get_nodes_by_type(self, node_type: NodeType) -> List[NodeResult]:
        """Get all node results of a specific type."""
        return [result for result in self.node_results if result.node_type == node_type]
    
    def mark_completed(self, final_output: Dict[str, Any] = None) -> None:
        """Mark the workflow execution as successfully completed."""
        self.status = ExecutionStatus.COMPLETED
        self.finished_at = datetime.utcnow()
        if final_output:
            self.output.update(final_output)
        
        # Update metrics
        if self.started_at:
            duration = (self.finished_at - self.started_at).total_seconds()
            self.metrics.total_duration_seconds = duration
    
    def mark_failed(self, error: ExecutionError) -> None:
        """Mark the workflow execution as failed."""
        self.status = ExecutionStatus.FAILED
        self.finished_at = datetime.utcnow()
        self.error = error
        
        # Update metrics
        if self.started_at:
            duration = (self.finished_at - self.started_at).total_seconds()
            self.metrics.total_duration_seconds = duration
    
    def mark_cancelled(self) -> None:
        """Mark the workflow execution as cancelled."""
        self.status = ExecutionStatus.CANCELLED
        self.finished_at = datetime.utcnow()
        
        # Update metrics
        if self.started_at:
            duration = (self.finished_at - self.started_at).total_seconds()
            self.metrics.total_duration_seconds = duration
    
    def add_node_result(self, result: NodeResult) -> None:
        """Add a node execution result."""
        # Remove existing result for the same node (in case of retries)
        self.node_results = [r for r in self.node_results if r.node_id != result.node_id]
        self.node_results.append(result)
        
        # Update context if available
        if self.context:
            self.context.add_node_result(result)
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """Get a summary of the execution results."""
        return {
            'run_id': self.run_id,
            'workflow_id': self.workflow_id,
            'status': self.status.value,
            'duration_seconds': self.duration_seconds,
            'success_rate': self.success_rate,
            'total_nodes': len(self.node_results),
            'successful_nodes': len(self.get_successful_nodes()),
            'failed_nodes': len(self.get_failed_nodes()),
            'total_retries': self.total_retries,
            'has_error': self.error is not None,
            'is_successful': self.is_successful,
            'started_at': self.started_at.isoformat(),
            'finished_at': self.finished_at.isoformat() if self.finished_at else None
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert execution result to dictionary representation."""
        result_dict = {
            'run_id': self.run_id,
            'workflow_id': self.workflow_id,
            'status': self.status.value,
            'started_at': self.started_at.isoformat(),
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'duration_seconds': self.duration_seconds,
            'output': self.output,
            'is_successful': self.is_successful,
            'is_failed': self.is_failed,
            'is_completed': self.is_completed,
            'success_rate': self.success_rate,
            'total_retries': self.total_retries,
            'node_results': [result.to_dict() for result in self.node_results],
            'summary': self.get_execution_summary()
        }
        
        if self.error:
            result_dict['error'] = self.error.to_dict()
        
        if self.context:
            result_dict['context'] = self.context.to_dict()
        
        return result_dict


# Factory functions for creating execution objects

def create_execution_context(run_id: str, alias_to_node_mapping: Optional[Dict[str, str]] = None) -> ExecutionContext:
    """Create a new execution context."""
    return ExecutionContext(
        run_id=run_id,
        alias_to_node_mapping=alias_to_node_mapping
    )


def create_node_result(node_id: str, node_type: NodeType, started_at: datetime = None) -> NodeResult:
    """Create a new node result."""
    return NodeResult(
        node_id=node_id,
        node_type=node_type,
        status=NodeExecutionStatus.PENDING,
        started_at=started_at or datetime.utcnow()
    )


def create_execution_result(run_id: str, workflow_id: str, started_at: datetime = None) -> ExecutionResult:
    """Create a new execution result."""
    return ExecutionResult(
        run_id=run_id,
        workflow_id=workflow_id,
        status=ExecutionStatus.PENDING,
        started_at=started_at or datetime.utcnow()
    )