"""
Workflow domain model for the AI Workflow Engine.

This module contains the core Workflow domain model with business logic
and validation rules according to Domain-Driven Design principles.

Author: AI Workflow Engine Team
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from ..enums.node_types import NodeType, TriggerRule
from ..exceptions.base import ValidationError


@dataclass
class WorkflowMetadata:
    """
    Metadata associated with a workflow definition.
    
    Contains non-functional information about the workflow
    such as creation time, version, and descriptive information.
    """
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    estimated_duration_minutes: Optional[int] = None
    
    def update_timestamp(self) -> None:
        """Update the last modified timestamp."""
        self.updated_at = datetime.utcnow()


@dataclass
class NodeConnection:
    """
    Represents a connection between two nodes in the workflow DAG.
    
    Defines the relationship between a source node and its target node(s),
    including any conditional logic that governs the connection.
    """
    
    source_node_id: str
    target_node_id: str
    condition: Optional[str] = None  # Expression that must be true for connection
    weight: int = 0  # Priority weight for execution order
    
    def __post_init__(self):
        """Validate connection data after initialization."""
        if not self.source_node_id or not self.source_node_id.strip():
            raise ValidationError("Source node ID cannot be empty")
        if not self.target_node_id or not self.target_node_id.strip():
            raise ValidationError("Target node ID cannot be empty")
        if self.source_node_id == self.target_node_id:
            raise ValidationError("Node cannot connect to itself")


@dataclass
class Node:
    """
    Represents a single node in the workflow DAG.
    
    Contains the node's configuration, type information, and execution parameters.
    This is the core building block of workflow definitions.
    """
    
    id: str
    type: NodeType
    config: Dict[str, Any] = field(default_factory=dict)
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_rule: TriggerRule = TriggerRule.ALL_SUCCESS
    timeout_seconds: int = 300  # 5 minutes default
    retry_count: int = 0
    depends_on: List[str] = field(default_factory=list)  # Upstream node IDs
    
    def __post_init__(self):
        """Validate node data after initialization."""
        self._validate_node()
    
    def _validate_node(self) -> None:
        """Validate node configuration and properties."""
        if not self.id or not self.id.strip():
            raise ValidationError("Node ID cannot be empty")
        
        if not isinstance(self.type, NodeType):
            raise ValidationError(f"Invalid node type: {self.type}")
        
        if self.timeout_seconds <= 0:
            raise ValidationError("Timeout must be positive")
        
        if self.retry_count < 0:
            raise ValidationError("Retry count cannot be negative")
        
        # Validate type-specific configuration
        self._validate_type_specific_config()
    
    def _validate_type_specific_config(self) -> None:
        """Validate configuration specific to the node type."""
        if self.type == NodeType.AGENT:
            self._validate_agent_config()
        elif self.type == NodeType.TOOL:
            self._validate_tool_config()
        elif self.type == NodeType.MCP_TOOL:
            self._validate_mcp_tool_config()
        elif self.type == NodeType.CONDITION:
            self._validate_condition_config()
    
    def _validate_agent_config(self) -> None:
        """Validate agent node configuration."""
        required_fields = ['provider', 'model', 'prompt']
        for field in required_fields:
            if field not in self.config:
                raise ValidationError(f"Agent node missing required config: {field}")
    
    def _validate_tool_config(self) -> None:
        """Validate tool node configuration."""
        if 'tool' not in self.config:
            raise ValidationError("Tool node missing required config: tool")
    
    def _validate_mcp_tool_config(self) -> None:
        """Validate MCP tool node configuration."""
        required_fields = ['server_id', 'tool']
        for field in required_fields:
            if field not in self.config:
                raise ValidationError(f"MCP tool node missing required config: {field}")
    
    def _validate_condition_config(self) -> None:
        """Validate condition node configuration."""
        if 'expression' not in self.config:
            raise ValidationError("Condition node missing required config: expression")
    
    @property
    def display_name(self) -> str:
        """Get the display name for this node."""
        return self.name or self.config.get('name', self.id)
    
    @property
    def is_start_node(self) -> bool:
        """Check if this is the workflow start node."""
        return self.type == NodeType.START
    
    @property
    def is_end_node(self) -> bool:
        """Check if this is the workflow end node."""
        return self.type == NodeType.END
    
    @property
    def requires_input(self) -> bool:
        """Check if this node requires input from upstream nodes."""
        return len(self.depends_on) > 0 and not self.is_start_node


@dataclass
class Workflow:
    """
    Core workflow domain model representing a complete workflow definition.
    
    This is the aggregate root for the workflow domain, containing all nodes,
    connections, and business logic for workflow validation and execution.
    """
    
    id: str
    name: str
    nodes: List[Node] = field(default_factory=list)
    connections: List[NodeConnection] = field(default_factory=list)
    description: Optional[str] = None
    metadata: WorkflowMetadata = field(default_factory=WorkflowMetadata)
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Validate workflow after initialization."""
        if not self.id:
            self.id = str(uuid4())
        self._validate_workflow()
    
    def _validate_workflow(self) -> None:
        """Validate the complete workflow definition."""
        if not self.name or not self.name.strip():
            raise ValidationError("Workflow name cannot be empty")
        
        if not self.nodes:
            raise ValidationError("Workflow must contain at least one node")
        
        # Validate individual components
        self._validate_node_ids_unique()
        self._validate_start_and_end_nodes()
        self._validate_connections()
        
        # Validate workflow structure
        validation_errors = self.validate_structure()
        if validation_errors:
            raise ValidationError(f"Workflow validation failed: {validation_errors}")
    
    def _validate_node_ids_unique(self) -> None:
        """Ensure all node IDs are unique."""
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            duplicates = [node_id for node_id in node_ids if node_ids.count(node_id) > 1]
            raise ValidationError(f"Duplicate node IDs found: {duplicates}")
    
    def _validate_start_and_end_nodes(self) -> None:
        """Validate presence of start and end nodes."""
        start_nodes = [node for node in self.nodes if node.is_start_node]
        end_nodes = [node for node in self.nodes if node.is_end_node]
        
        if len(start_nodes) != 1:
            raise ValidationError(f"Workflow must have exactly one start node, found {len(start_nodes)}")
        
        if len(end_nodes) < 1:
            raise ValidationError("Workflow must have at least one end node")
    
    def _validate_connections(self) -> None:
        """Validate all node connections reference valid nodes."""
        node_ids = {node.id for node in self.nodes}
        
        for connection in self.connections:
            if connection.source_node_id not in node_ids:
                raise ValidationError(f"Connection references unknown source node: {connection.source_node_id}")
            if connection.target_node_id not in node_ids:
                raise ValidationError(f"Connection references unknown target node: {connection.target_node_id}")
    
    def get_start_node(self) -> Optional[Node]:
        """Find and return the workflow start node."""
        start_nodes = [node for node in self.nodes if node.is_start_node]
        return start_nodes[0] if start_nodes else None
    
    def get_end_nodes(self) -> List[Node]:
        """Find and return all workflow end nodes."""
        return [node for node in self.nodes if node.is_end_node]
    
    def get_node_by_id(self, node_id: str) -> Optional[Node]:
        """Get a node by its ID."""
        return next((node for node in self.nodes if node.id == node_id), None)
    
    def get_node_dependencies(self, node_id: str) -> List[Node]:
        """Get all nodes that this node depends on."""
        node = self.get_node_by_id(node_id)
        if not node:
            return []
        
        return [self.get_node_by_id(dep_id) for dep_id in node.depends_on 
                if self.get_node_by_id(dep_id) is not None]
    
    def get_node_dependents(self, node_id: str) -> List[Node]:
        """Get all nodes that depend on this node."""
        dependents = []
        for node in self.nodes:
            if node_id in node.depends_on:
                dependents.append(node)
        return dependents
    
    def validate_structure(self) -> List[str]:
        """
        Validate the workflow DAG structure.
        
        Returns a list of validation error messages.
        Empty list indicates valid structure.
        """
        errors = []
        
        # Check for cycles in the DAG
        if self._has_cycles():
            errors.append("Workflow contains cycles - DAGs cannot have circular dependencies")
        
        # Check for unreachable nodes
        unreachable = self._find_unreachable_nodes()
        if unreachable:
            errors.append(f"Unreachable nodes found: {unreachable}")
        
        # Check for nodes with no path to end
        no_end_path = self._find_nodes_with_no_end_path()
        if no_end_path:
            errors.append(f"Nodes with no path to end: {no_end_path}")
        
        return errors
    
    def _has_cycles(self) -> bool:
        """Check if the workflow DAG contains cycles using DFS."""
        # Color coding: 0=white (unvisited), 1=gray (visiting), 2=black (visited)
        colors = {node.id: 0 for node in self.nodes}
        
        def dfs(node_id: str) -> bool:
            if colors[node_id] == 1:  # Gray - cycle detected
                return True
            if colors[node_id] == 2:  # Black - already processed
                return False
            
            colors[node_id] = 1  # Mark as gray (visiting)
            
            # Visit all dependent nodes
            for dependent in self.get_node_dependents(node_id):
                if dfs(dependent.id):
                    return True
            
            colors[node_id] = 2  # Mark as black (visited)
            return False
        
        # Check for cycles starting from each unvisited node
        for node in self.nodes:
            if colors[node.id] == 0:
                if dfs(node.id):
                    return True
        
        return False
    
    def _find_unreachable_nodes(self) -> List[str]:
        """Find nodes that cannot be reached from the start node."""
        start_node = self.get_start_node()
        if not start_node:
            return []
        
        reachable = set()
        
        def mark_reachable(node_id: str):
            if node_id in reachable:
                return
            reachable.add(node_id)
            
            # Mark all dependent nodes as reachable
            for dependent in self.get_node_dependents(node_id):
                mark_reachable(dependent.id)
        
        mark_reachable(start_node.id)
        
        all_node_ids = {node.id for node in self.nodes}
        unreachable = all_node_ids - reachable
        
        return list(unreachable)
    
    def _find_nodes_with_no_end_path(self) -> List[str]:
        """Find nodes that have no path to any end node."""
        end_nodes = self.get_end_nodes()
        if not end_nodes:
            return []
        
        can_reach_end = set()
        
        def mark_can_reach_end(node_id: str):
            if node_id in can_reach_end:
                return
            can_reach_end.add(node_id)
            
            # Mark all dependency nodes as able to reach end
            for dependency in self.get_node_dependencies(node_id):
                mark_can_reach_end(dependency.id)
        
        # Start from all end nodes and work backwards
        for end_node in end_nodes:
            mark_can_reach_end(end_node.id)
        
        all_node_ids = {node.id for node in self.nodes}
        no_end_path = all_node_ids - can_reach_end
        
        return list(no_end_path)
    
    def add_node(self, node: Node) -> None:
        """Add a node to the workflow."""
        if self.get_node_by_id(node.id):
            raise ValidationError(f"Node with ID {node.id} already exists")
        
        self.nodes.append(node)
        self.metadata.update_timestamp()
    
    def remove_node(self, node_id: str) -> bool:
        """Remove a node from the workflow."""
        node = self.get_node_by_id(node_id)
        if not node:
            return False
        
        # Remove the node
        self.nodes.remove(node)
        
        # Remove all connections involving this node
        self.connections = [
            conn for conn in self.connections 
            if conn.source_node_id != node_id and conn.target_node_id != node_id
        ]
        
        # Remove from dependencies of other nodes
        for other_node in self.nodes:
            if node_id in other_node.depends_on:
                other_node.depends_on.remove(node_id)
        
        self.metadata.update_timestamp()
        return True
    
    def add_connection(self, connection: NodeConnection) -> None:
        """Add a connection between nodes."""
        # Validate nodes exist
        if not self.get_node_by_id(connection.source_node_id):
            raise ValidationError(f"Source node not found: {connection.source_node_id}")
        if not self.get_node_by_id(connection.target_node_id):
            raise ValidationError(f"Target node not found: {connection.target_node_id}")
        
        # Add to connections and update target node dependencies
        self.connections.append(connection)
        target_node = self.get_node_by_id(connection.target_node_id)
        if target_node and connection.source_node_id not in target_node.depends_on:
            target_node.depends_on.append(connection.source_node_id)
        
        self.metadata.update_timestamp()
    
    @property
    def node_count(self) -> int:
        """Get the total number of nodes in the workflow."""
        return len(self.nodes)
    
    @property
    def connection_count(self) -> int:
        """Get the total number of connections in the workflow."""
        return len(self.connections)
    
    @property
    def is_valid(self) -> bool:
        """Check if the workflow is structurally valid."""
        try:
            validation_errors = self.validate_structure()
            return len(validation_errors) == 0
        except ValidationError:
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary representation."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'nodes': [
                {
                    'id': node.id,
                    'type': node.type.value,
                    'name': node.name,
                    'config': node.config,
                    'trigger_rule': node.trigger_rule.value,
                    'timeout_seconds': node.timeout_seconds,
                    'retry_count': node.retry_count,
                    'depends_on': node.depends_on
                }
                for node in self.nodes
            ],
            'connections': [
                {
                    'source': conn.source_node_id,
                    'target': conn.target_node_id,
                    'condition': conn.condition,
                    'weight': conn.weight
                }
                for conn in self.connections
            ],
            'metadata': {
                'created_at': self.metadata.created_at.isoformat(),
                'updated_at': self.metadata.updated_at.isoformat(),
                'version': self.metadata.version,
                'author': self.metadata.author,
                'tags': self.metadata.tags
            }
        }