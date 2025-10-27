"""
Execution status enumerations for the AI Workflow Engine.

This module defines the various states that workflow executions and nodes
can be in during their lifecycle.

Author: AI Workflow Engine Team
"""

from enum import Enum


class ExecutionStatus(str, Enum):
    """
    Enumeration of workflow execution statuses.
    
    These statuses represent the various states a workflow execution
    can be in throughout its lifecycle.
    """
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    
    @property
    def is_terminal(self) -> bool:
        """Check if this status represents a terminal state."""
        return self in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMEOUT
        )
    
    @property
    def is_successful(self) -> bool:
        """Check if this status represents a successful completion."""
        return self == ExecutionStatus.COMPLETED
    
    @property
    def is_error(self) -> bool:
        """Check if this status represents an error state."""
        return self in (
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMEOUT
        )


class NodeExecutionStatus(str, Enum):
    """
    Enumeration of individual node execution statuses.
    
    These statuses represent the various states an individual node
    can be in during execution.
    """
    
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    
    @property
    def is_terminal(self) -> bool:
        """Check if this status represents a terminal state."""
        return self in (
            NodeExecutionStatus.SUCCESS,
            NodeExecutionStatus.FAILED,
            NodeExecutionStatus.SKIPPED,
            NodeExecutionStatus.TIMEOUT
        )
    
    @property
    def is_successful(self) -> bool:
        """Check if this status represents a successful completion."""
        return self == NodeExecutionStatus.SUCCESS
    
    @property
    def is_error(self) -> bool:
        """Check if this status represents an error state."""
        return self in (
            NodeExecutionStatus.FAILED,
            NodeExecutionStatus.TIMEOUT
        )