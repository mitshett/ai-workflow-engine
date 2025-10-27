"""
Validation service for the AI Workflow Engine.

This service handles comprehensive validation of workflows, including:
- Workflow definition parsing and validation
- Schema validation for input/output data
- Business rule validation
- Node configuration validation
- DAG structure validation

Author: AI Workflow Engine Team
"""

import logging
from typing import Dict, List, Optional, Any
from uuid import uuid4

from ..domain.models import (
    Workflow,
    Node,
    NodeConnection,
    WorkflowMetadata,
)
from ..domain.enums.node_types import NodeType, TriggerRule
from ..domain.exceptions.base import (
    ValidationError,
    BusinessLogicException,
)


class ValidationService:
    """
    Comprehensive validation service for workflows and related data.
    
    This service provides validation for:
    - Workflow definitions (JSON/YAML parsing)
    - Schema validation for input/output data
    - Business rule validation
    - Node configuration validation
    - DAG structure and dependency validation
    """
    
    def __init__(self):
        """Initialize the validation service."""
        self.logger = logging.getLogger(__name__)
        
        # Schema definitions for different node types
        self._node_schemas = self._initialize_node_schemas()
    
    async def parse_and_validate_workflow(
        self,
        definition: Dict[str, Any],
        name: Optional[str] = None,
        description: Optional[str] = None,
        workflow_id: Optional[str] = None
    ) -> Workflow:
        """
        Parse and validate a complete workflow definition.
        
        Args:
            definition: Workflow definition dictionary
            name: Optional workflow name override
            description: Optional workflow description override
            workflow_id: Optional workflow ID override
            
        Returns:
            Validated Workflow domain object
            
        Raises:
            ValidationError: If definition is invalid
        """
        self.logger.info(
            "Starting workflow validation",
            extra={
                "definition_keys": list(definition.keys()),
                "override_name": name is not None,
                "override_id": workflow_id is not None
            }
        )
        
        try:
            # 1. Validate basic structure
            await self._validate_workflow_structure(definition)
            
            # 2. Extract and validate basic properties
            workflow_name = name or definition.get('name')
            workflow_description = description or definition.get('description')
            workflow_id = workflow_id or definition.get('id', str(uuid4()))
            
            if not workflow_name:
                raise ValidationError("Workflow name is required")
            
            # 3. Parse and validate nodes
            nodes = await self._parse_and_validate_nodes(definition.get('nodes', []))
            
            # 4. Parse and validate connections
            connections = await self._parse_and_validate_connections(
                definition.get('connections', []),
                nodes,
                nodes_data=definition.get('nodes', [])
            )
            
            # 5. Sync node dependencies with extracted connections
            await self._sync_node_dependencies_with_connections(nodes, connections)
            
            # 6. Create metadata
            metadata = await self._parse_metadata(definition.get('metadata', {}))
            
            # 7. Parse schemas
            input_schema = definition.get('input_schema')
            output_schema = definition.get('output_schema')
            
            if input_schema:
                await self._validate_schema_definition(input_schema, "input_schema")
            if output_schema:
                await self._validate_schema_definition(output_schema, "output_schema")
            
            # 8. Create workflow object (this will run domain validations)
            workflow = Workflow(
                id=workflow_id,
                name=workflow_name,
                description=workflow_description,
                nodes=nodes,
                connections=connections,
                metadata=metadata,
                input_schema=input_schema,
                output_schema=output_schema
            )
            
            # 9. Additional business rule validation
            await self._validate_business_rules(workflow)
            
            self.logger.info(
                "Workflow validation completed successfully",
                extra={
                    "workflow_id": workflow.id,
                    "node_count": len(workflow.nodes),
                    "connection_count": len(workflow.connections),
                    "is_valid": workflow.is_valid
                }
            )
            
            return workflow
            
        except Exception as e:
            self.logger.error(
                "Workflow validation failed",
                extra={
                    "error": str(e),
                    "error_type": e.__class__.__name__,
                    "definition_keys": list(definition.keys()) if isinstance(definition, dict) else "not_dict"
                }
            )
            raise
    
    async def validate_input_data(
        self,
        input_data: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> None:
        """
        Validate input data against a schema.
        
        Args:
            input_data: Input data to validate
            schema: Schema definition to validate against
            
        Raises:
            ValidationError: If input data is invalid
        """
        self.logger.debug(
            "Validating input data",
            extra={
                "input_keys": list(input_data.keys()),
                "schema_keys": list(schema.keys()) if isinstance(schema, dict) else "not_dict"
            }
        )
        
        await self._validate_data_against_schema(input_data, schema, "input_data")
    
    async def validate_node_configuration(
        self,
        node_type: NodeType,
        config: Dict[str, Any]
    ) -> None:
        """
        Validate node configuration for a specific node type.
        
        Args:
            node_type: Type of node
            config: Configuration to validate
            
        Raises:
            ValidationError: If configuration is invalid
        """
        if node_type not in self._node_schemas:
            raise ValidationError(f"Unknown node type: {node_type}")
        
        schema = self._node_schemas[node_type]
        await self._validate_data_against_schema(config, schema, f"{node_type.value}_config")
    
    # Private validation methods
    
    async def _validate_workflow_structure(self, definition: Dict[str, Any]) -> None:
        """
        Validate basic workflow definition structure.
        
        Args:
            definition: Workflow definition to validate
            
        Raises:
            ValidationError: If structure is invalid
        """
        if not isinstance(definition, dict):
            raise ValidationError("Workflow definition must be a dictionary")
        
        # Check for required top-level keys
        if 'nodes' not in definition:
            raise ValidationError("Workflow definition must contain 'nodes'")
        
        if not isinstance(definition['nodes'], list):
            raise ValidationError("'nodes' must be a list")
        
        if len(definition['nodes']) == 0:
            raise ValidationError("Workflow must contain at least one node")
        
        # Validate optional fields
        if 'connections' in definition and not isinstance(definition['connections'], list):
            raise ValidationError("'connections' must be a list")
        
        if 'metadata' in definition and not isinstance(definition['metadata'], dict):
            raise ValidationError("'metadata' must be a dictionary")
    
    async def _parse_and_validate_nodes(self, nodes_data: List[Dict[str, Any]]) -> List[Node]:
        """
        Parse and validate node definitions.
        
        Args:
            nodes_data: List of node definition dictionaries
            
        Returns:
            List of validated Node objects
            
        Raises:
            ValidationError: If any node is invalid
        """
        nodes = []
        node_ids = set()
        
        for i, node_data in enumerate(nodes_data):
            try:
                node = await self._parse_and_validate_single_node(node_data)
                
                # Check for duplicate IDs
                if node.id in node_ids:
                    raise ValidationError(f"Duplicate node ID: {node.id}")
                
                node_ids.add(node.id)
                nodes.append(node)
                
            except Exception as e:
                raise ValidationError(f"Invalid node at index {i}: {str(e)}")
        
        # Validate node type requirements
        await self._validate_node_type_requirements(nodes)
        
        return nodes
    
    async def _parse_and_validate_single_node(self, node_data: Dict[str, Any]) -> Node:
        """
        Parse and validate a single node definition.
        
        Args:
            node_data: Node definition dictionary
            
        Returns:
            Validated Node object
            
        Raises:
            ValidationError: If node is invalid
        """
        # Validate required fields
        if 'id' not in node_data:
            raise ValidationError("Node missing required field: id")
        
        if 'type' not in node_data:
            raise ValidationError("Node missing required field: type")
        
        # Parse node type
        try:
            node_type = NodeType(node_data['type'])
        except ValueError:
            valid_types = [t.value for t in NodeType]
            raise ValidationError(
                f"Invalid node type '{node_data['type']}'. Valid types: {valid_types}"
            )
        
        # Parse trigger rule
        trigger_rule = TriggerRule.ALL_SUCCESS  # default
        if 'trigger_rule' in node_data:
            try:
                trigger_rule = TriggerRule(node_data['trigger_rule'])
            except ValueError:
                valid_rules = [r.value for r in TriggerRule]
                raise ValidationError(
                    f"Invalid trigger rule '{node_data['trigger_rule']}'. Valid rules: {valid_rules}"
                )
        
        # Validate configuration
        config = node_data.get('config', {})
        if not isinstance(config, dict):
            raise ValidationError("Node config must be a dictionary")
        
        await self.validate_node_configuration(node_type, config)
        
        # Parse dependencies
        depends_on = node_data.get('depends_on', [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        elif not isinstance(depends_on, list):
            raise ValidationError("Node 'depends_on' must be a string or list of strings")
        
        # Create node object
        node = Node(
            id=node_data['id'],
            type=node_type,
            name=node_data.get('name'),
            description=node_data.get('description'),
            config=config,
            trigger_rule=trigger_rule,
            timeout_seconds=node_data.get('timeout_seconds', 300),
            retry_count=node_data.get('retry_count', 0),
            depends_on=depends_on
        )
        
        return node
    
    async def _parse_and_validate_connections(
        self,
        connections_data: List[Dict[str, Any]],
        nodes: List[Node],
        nodes_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[NodeConnection]:
        """
        Parse and validate connection definitions.
        
        Supports two formats:
        1. Explicit connections array with source/target
        2. Implicit connections via "next" fields in nodes
        
        Args:
            connections_data: List of connection definition dictionaries
            nodes: List of nodes for validation
            nodes_data: Optional list of raw node data for "next" field parsing
            
        Returns:
            List of validated NodeConnection objects
            
        Raises:
            ValidationError: If any connection is invalid
        """
        connections = []
        node_ids = {node.id for node in nodes}
        
        # If no explicit connections but nodes have "next" fields, parse them
        if not connections_data and nodes_data:
            self.logger.info("No explicit connections found, parsing from node 'next' fields")
            connections_data = await self._extract_connections_from_nodes(nodes_data)
        
        for i, conn_data in enumerate(connections_data):
            try:
                # Validate required fields
                if 'source' not in conn_data:
                    raise ValidationError("Connection missing required field: source")
                if 'target' not in conn_data:
                    raise ValidationError("Connection missing required field: target")
                
                # Validate node references
                source_id = conn_data['source']
                target_id = conn_data['target']
                
                if source_id not in node_ids:
                    raise ValidationError(f"Connection references unknown source node: {source_id}")
                if target_id not in node_ids:
                    raise ValidationError(f"Connection references unknown target node: {target_id}")
                
                # Create connection
                connection = NodeConnection(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    condition=conn_data.get('condition'),
                    weight=conn_data.get('weight', 0)
                )
                
                connections.append(connection)
                
            except Exception as e:
                raise ValidationError(f"Invalid connection at index {i}: {str(e)}")
        
        return connections
    
    async def _extract_connections_from_nodes(self, nodes_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract connections from node "next" fields.
        
        Converts payload format like:
        {"id": "node1", "next": ["node2", "node3"]}
        
        To connection format like:
        [{"source": "node1", "target": "node2"}, {"source": "node1", "target": "node3"}]
        
        Args:
            nodes_data: List of raw node data dictionaries
            
        Returns:
            List of connection dictionaries in expected format
        """
        connections_data = []
        
        for node_data in nodes_data:
            node_id = node_data.get('id')
            next_nodes = node_data.get('next', [])
            
            if not node_id:
                continue
                
            # Handle next field (can be string or list)
            if isinstance(next_nodes, str):
                next_nodes = [next_nodes]
            elif not isinstance(next_nodes, list):
                continue
            
            # Create connections for each "next" target
            for target_id in next_nodes:
                if isinstance(target_id, str) and target_id.strip():
                    connections_data.append({
                        'source': node_id,
                        'target': target_id.strip(),
                        'weight': 0
                    })
        
        self.logger.info(f"Extracted {len(connections_data)} connections from node 'next' fields")
        return connections_data
    
    async def _sync_node_dependencies_with_connections(
        self, 
        nodes: List[Node], 
        connections: List[NodeConnection]
    ) -> None:
        """
        Synchronize node dependencies with the connection list.
        
        This ensures that each node's depends_on list matches the connections
        that target that node, which is critical for DAG validation.
        
        Args:
            nodes: List of nodes to update
            connections: List of connections to use for dependency updates
        """
        # Create a mapping of target node -> source nodes
        target_to_sources = {}
        for connection in connections:
            target_id = connection.target_node_id
            source_id = connection.source_node_id
            
            if target_id not in target_to_sources:
                target_to_sources[target_id] = []
            target_to_sources[target_id].append(source_id)
        
        # Update each node's dependencies based on connections
        for node in nodes:
            expected_dependencies = target_to_sources.get(node.id, [])
            
            # Update the node's depends_on list to match connections
            node.depends_on = list(set(expected_dependencies))  # Remove duplicates
            
            self.logger.debug(f"Updated node {node.id} dependencies: {node.depends_on}")
        
        self.logger.info(f"Synchronized node dependencies with {len(connections)} connections")
    
    async def _parse_metadata(self, metadata_data: Dict[str, Any]) -> WorkflowMetadata:
        """
        Parse workflow metadata.
        
        Args:
            metadata_data: Metadata dictionary
            
        Returns:
            WorkflowMetadata object
        """
        return WorkflowMetadata(
            version=metadata_data.get('version', '1.0.0'),
            author=metadata_data.get('author'),
            tags=metadata_data.get('tags', []),
            estimated_duration_minutes=metadata_data.get('estimated_duration_minutes')
        )
    
    async def _validate_node_type_requirements(self, nodes: List[Node]) -> None:
        """
        Validate node type requirements (e.g., exactly one start node).
        
        Args:
            nodes: List of nodes to validate
            
        Raises:
            ValidationError: If requirements are not met
        """
        start_nodes = [node for node in nodes if node.type == NodeType.START]
        end_nodes = [node for node in nodes if node.type == NodeType.END]
        
        if len(start_nodes) == 0:
            raise ValidationError("Workflow must have at least one START node")
        if len(start_nodes) > 1:
            start_ids = [node.id for node in start_nodes]
            raise ValidationError(f"Workflow can have only one START node, found: {start_ids}")
        
        if len(end_nodes) == 0:
            raise ValidationError("Workflow must have at least one END node")
    
    async def _validate_business_rules(self, workflow: Workflow) -> None:
        """
        Validate business rules for the workflow.
        
        Args:
            workflow: Workflow to validate
            
        Raises:
            BusinessLogicException: If business rules are violated
        """
        # Check for unreachable nodes
        validation_errors = workflow.validate_structure()
        if validation_errors:
            raise BusinessLogicException(
                f"Workflow structure validation failed: {validation_errors}",
                rule="valid_dag_structure",
                details={"validation_errors": validation_errors}
            )
        
        # Validate node dependencies exist
        node_ids = {node.id for node in workflow.nodes}
        for node in workflow.nodes:
            for dep_id in node.depends_on:
                if dep_id not in node_ids:
                    raise BusinessLogicException(
                        f"Node {node.id} depends on non-existent node: {dep_id}",
                        rule="valid_dependencies",
                        details={"node_id": node.id, "missing_dependency": dep_id}
                    )
        
        # Validate start node has no dependencies
        start_node = workflow.get_start_node()
        if start_node and start_node.depends_on:
            raise BusinessLogicException(
                "START node cannot have dependencies",
                rule="start_node_no_dependencies",
                details={"start_node_id": start_node.id, "dependencies": start_node.depends_on}
            )
    
    async def _validate_schema_definition(
        self,
        schema: Dict[str, Any],
        schema_name: str
    ) -> None:
        """
        Validate a schema definition.
        
        Args:
            schema: Schema definition to validate
            schema_name: Name of schema for error messages
            
        Raises:
            ValidationError: If schema is invalid
        """
        if not isinstance(schema, dict):
            raise ValidationError(f"{schema_name} must be a dictionary")
        
        # Basic schema validation - could be enhanced with JSON Schema
        for key, definition in schema.items():
            if not isinstance(key, str):
                raise ValidationError(f"{schema_name} keys must be strings")
            
            if not isinstance(definition, dict):
                raise ValidationError(f"{schema_name}.{key} must be a dictionary")
            
            # Validate required fields in schema definition
            if 'type' not in definition:
                raise ValidationError(f"{schema_name}.{key} missing required 'type' field")
    
    async def _validate_data_against_schema(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any],
        data_name: str
    ) -> None:
        """
        Validate data against a schema definition.
        
        Args:
            data: Data to validate
            schema: Schema definition
            data_name: Name of data for error messages
            
        Raises:
            ValidationError: If data doesn't match schema
        """
        if not isinstance(data, dict):
            raise ValidationError(f"{data_name} must be a dictionary")
        
        # Validate required fields
        for key, definition in schema.items():
            if definition.get('required', False) and key not in data:
                raise ValidationError(f"{data_name} missing required field: {key}")
        
        # Validate field types
        for key, value in data.items():
            if key in schema:
                expected_type = schema[key].get('type')
                if expected_type and not self._validate_type(value, expected_type):
                    raise ValidationError(
                        f"{data_name}.{key} has invalid type. Expected: {expected_type}, got: {type(value).__name__}"
                    )
    
    def _validate_type(self, value: Any, expected_type: str) -> bool:
        """
        Validate that a value matches the expected type.
        
        Args:
            value: Value to validate
            expected_type: Expected type string
            
        Returns:
            True if value matches expected type
        """
        type_mapping = {
            'string': str,
            'integer': int,
            'number': (int, float),
            'boolean': bool,
            'array': list,
            'object': dict,
            'null': type(None)
        }
        
        expected_python_type = type_mapping.get(expected_type)
        if expected_python_type is None:
            return True  # Unknown type, accept anything
        
        return isinstance(value, expected_python_type)
    
    def _initialize_node_schemas(self) -> Dict[NodeType, Dict[str, Any]]:
        """
        Initialize schema definitions for different node types.
        
        Returns:
            Dictionary mapping node types to their schema definitions
        """
        return {
            NodeType.START: {
                # START nodes typically don't need configuration
            },
            NodeType.END: {
                # END nodes typically don't need configuration
            },
            NodeType.AGENT: {
                'provider': {'type': 'string', 'required': True},
                'model': {'type': 'string', 'required': True},
                'prompt': {'type': 'string', 'required': True},
                'max_tokens': {'type': 'integer', 'required': False},
                'temperature': {'type': 'number', 'required': False},
                'system_prompt': {'type': 'string', 'required': False}
            },
            NodeType.TOOL: {
                'tool': {'type': 'string', 'required': True},
                'arguments': {'type': 'object', 'required': False},
                'timeout': {'type': 'integer', 'required': False}
            },
            NodeType.MCP_TOOL: {
                'server_id': {'type': 'string', 'required': True},
                'tool': {'type': 'string', 'required': True},
                'arguments': {'type': 'object', 'required': False},
                'timeout': {'type': 'integer', 'required': False}
            },
            NodeType.CONDITION: {
                'expression': {'type': 'string', 'required': True},
                'true_branch': {'type': 'array', 'required': False},
                'false_branch': {'type': 'array', 'required': False}
            }
        }