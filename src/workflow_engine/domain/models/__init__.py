"""
Domain models for the AI Workflow Engine.

This module exports all domain models used throughout the application.
These models represent the core business entities and contain the
business logic and validation rules.

Author: AI Workflow Engine Team
"""

from .workflow import (
    Workflow,
    Node,
    NodeConnection,
    WorkflowMetadata,
)

from .execution import (
    ExecutionResult,
    NodeResult,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionError,
    create_execution_context,
    create_node_result,
    create_execution_result,
)

__all__ = [
    # Workflow models
    "Workflow",
    "Node", 
    "NodeConnection",
    "WorkflowMetadata",
    
    # Execution models
    "ExecutionResult",
    "NodeResult",
    "ExecutionContext",
    "ExecutionMetrics",
    "ExecutionError",
    
    # Factory functions
    "create_execution_context",
    "create_node_result", 
    "create_execution_result",
]