"""
Node type enumerations for the AI Workflow Engine.

This module defines the various types of nodes that can be used
in workflow definitions.

Author: AI Workflow Engine Team
"""

from enum import Enum


class NodeType(str, Enum):
    """
    Enumeration of supported workflow node types.
    
    These node types define the different kinds of operations
    that can be performed within a workflow.
    """
    
    START = "start"
    END = "end"
    AGENT = "agent"
    TOOL = "tool"
    MCP_TOOL = "mcp_tool"
    CONDITION = "condition"
    
    @property
    def is_control_node(self) -> bool:
        """Check if this node type is a control flow node."""
        return self in (NodeType.START, NodeType.END, NodeType.CONDITION)
    
    @property
    def is_execution_node(self) -> bool:
        """Check if this node type performs actual work."""
        return self in (NodeType.AGENT, NodeType.TOOL, NodeType.MCP_TOOL)
    
    @property
    def requires_configuration(self) -> bool:
        """Check if this node type requires specific configuration."""
        return self in (NodeType.AGENT, NodeType.TOOL, NodeType.MCP_TOOL, NodeType.CONDITION)


class TriggerRule(str, Enum):
    """
    Enumeration of node execution trigger rules.
    
    These rules determine when a node should be executed based
    on the status of its upstream dependencies.
    """
    
    ALL_SUCCESS = "all_success"      # All upstream nodes must succeed
    ONE_SUCCESS = "one_success"      # At least one upstream node succeeded
    ALL_DONE = "all_done"            # All upstream nodes completed (success or failure)
    ALWAYS = "always"                # Execute regardless of upstream status
    NONE_FAILED = "none_failed"      # Execute if no upstream nodes failed
    
    @property
    def description(self) -> str:
        """Get human-readable description of the trigger rule."""
        descriptions = {
            TriggerRule.ALL_SUCCESS: "All upstream nodes must succeed",
            TriggerRule.ONE_SUCCESS: "At least one upstream node must succeed",
            TriggerRule.ALL_DONE: "All upstream nodes must complete (regardless of status)",
            TriggerRule.ALWAYS: "Execute regardless of upstream node status",
            TriggerRule.NONE_FAILED: "Execute if no upstream nodes failed"
        }
        return descriptions.get(self, "Unknown trigger rule")