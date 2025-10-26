"""AI Workflow Engine - Workflow Definition Parser

Comprehensive parser for workflow definitions with support for:
- Multiple input formats (JSON, YAML, dict, string)
- Template variable validation and resolution
- Performance-optimized validation modes
- Detailed error reporting with line numbers
- Integration with Pydantic schema validation
"""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import yaml
from pydantic import ValidationError as PydanticValidationError

from .schemas import (
    WorkflowDefinition,
    WorkflowNode,
    StartNodeConfig,
    EndNodeConfig,
    AgentNodeConfig,
    ToolNodeConfig,
    MCPToolNodeConfig,
    ConditionNodeConfig,
    ValidationResult,
    ValidationError,
    NodeType,
)


class ParsedWorkflowResult:
    """Result of workflow parsing with comprehensive validation info."""

    def __init__(
        self,
        workflow: Optional[WorkflowDefinition] = None,
        validation_result: Optional[ValidationResult] = None,
        is_valid: bool = False,
        parse_time_ms: float = 0.0,
        source_info: Optional[Dict[str, Any]] = None,
    ):
        self.workflow = workflow
        self.validation_result = validation_result or ValidationResult(valid=is_valid)
        self.is_valid = is_valid
        self.parse_time_ms = parse_time_ms
        self.source_info = source_info or {}

    def get_error_summary(self) -> str:
        """Get human-readable error summary."""
        if self.is_valid:
            return "✅ Workflow validation passed"

        error_count = len(self.validation_result.errors)
        warning_count = len(self.validation_result.warnings)

        summary = f"❌ Validation failed with {error_count} error(s)"
        if warning_count > 0:
            summary += f" and {warning_count} warning(s)"

        return summary

    def get_detailed_errors(self) -> List[str]:
        """Get detailed error messages."""
        messages = []

        for error in self.validation_result.errors:
            msg = f"❌ {error.field}: {error.message}"
            if error.node_id:
                msg += f" (in node '{error.node_id}')"
            messages.append(msg)

        for warning in self.validation_result.warnings:
            messages.append(f"⚠️  {warning}")

        return messages


class WorkflowDefinitionParser:
    """Parser for AI workflow definitions with comprehensive validation."""

    def __init__(
        self,
        strict_validation: bool = True,
        performance_mode: bool = False,
        validate_templates: bool = True,
    ):
        """Initialize the workflow parser.

        Args:
            strict_validation: Enable comprehensive validation checks
            performance_mode: Optimize for speed over thoroughness
            validate_templates: Validate template variable references
        """
        self.strict_validation = strict_validation
        self.performance_mode = performance_mode
        self.validate_templates = validate_templates

        # Template variable pattern: ${variable.path}
        self.template_pattern = re.compile(r'\$\{([^}]+)\}')

        # Node type to config class mapping
        self.node_config_classes = {
            NodeType.START: StartNodeConfig,
            NodeType.END: EndNodeConfig,
            NodeType.AGENT: AgentNodeConfig,
            NodeType.TOOL: ToolNodeConfig,
            NodeType.MCP_TOOL: MCPToolNodeConfig,
            NodeType.CONDITION: ConditionNodeConfig,
        }

    # ========================================================================
    # PUBLIC API - MAIN ENTRY POINTS
    # ========================================================================

    def parse_file(self, file_path: Union[str, Path]) -> ParsedWorkflowResult:
        """Parse workflow from file (JSON or YAML)."""
        start_time = time.time()
        file_path = Path(file_path)

        try:
            if not file_path.exists():
                return self._create_error_result(
                    f"File not found: {file_path}",
                    parse_time_ms=(time.time() - start_time) * 1000,
                )

            # Read file content
            content = file_path.read_text(encoding="utf-8")

            # Determine format and parse
            if file_path.suffix.lower() in [".yaml", ".yml"]:
                return self._parse_yaml_content(content, str(file_path), start_time)
            elif file_path.suffix.lower() == ".json":
                return self._parse_json_content(content, str(file_path), start_time)
            else:
                return self._create_error_result(
                    f"Unsupported file format: {file_path.suffix}. Use .json, .yaml, or .yml",
                    parse_time_ms=(time.time() - start_time) * 1000,
                )

        except Exception as e:
            return self._create_error_result(
                f"Failed to read file {file_path}: {str(e)}",
                parse_time_ms=(time.time() - start_time) * 1000,
            )

    def parse_string(self, content: str, format_hint: str = "auto") -> ParsedWorkflowResult:
        """Parse workflow from string content."""
        start_time = time.time()

        if format_hint == "auto":
            # Auto-detect format
            content_stripped = content.strip()
            if content_stripped.startswith("{") or content_stripped.startswith("["):
                format_hint = "json"
            else:
                format_hint = "yaml"

        if format_hint.lower() == "json":
            return self._parse_json_content(content, "<string>", start_time)
        elif format_hint.lower() in ["yaml", "yml"]:
            return self._parse_yaml_content(content, "<string>", start_time)
        else:
            return self._create_error_result(
                f"Invalid format hint: {format_hint}. Use 'json' or 'yaml'",
                parse_time_ms=(time.time() - start_time) * 1000,
            )

    def parse_dict(self, data: Dict[str, Any]) -> ParsedWorkflowResult:
        """Parse workflow from Python dictionary."""
        start_time = time.time()
        return self._parse_workflow_data(data, "<dict>", start_time)

    # ========================================================================
    # INTERNAL PARSING METHODS
    # ========================================================================

    def _parse_json_content(self, content: str, source: str, start_time: float) -> ParsedWorkflowResult:
        """Parse JSON content with error handling."""
        try:
            data = json.loads(content)
            return self._parse_workflow_data(data, source, start_time)
        except json.JSONDecodeError as e:
            return self._create_error_result(
                f"Invalid JSON syntax at line {e.lineno}, column {e.colno}: {e.msg}",
                parse_time_ms=(time.time() - start_time) * 1000,
                source_info={"source": source, "line": e.lineno, "column": e.colno},
            )

    def _parse_yaml_content(self, content: str, source: str, start_time: float) -> ParsedWorkflowResult:
        """Parse YAML content with error handling."""
        try:
            data = yaml.safe_load(content)
            return self._parse_workflow_data(data, source, start_time)
        except yaml.YAMLError as e:
            error_msg = f"Invalid YAML syntax: {str(e)}"
            source_info = {"source": source}

            if hasattr(e, "problem_mark"):
                line = e.problem_mark.line + 1
                column = e.problem_mark.column + 1
                error_msg += f" at line {line}, column {column}"
                source_info.update({"line": line, "column": column})

            return self._create_error_result(
                error_msg,
                parse_time_ms=(time.time() - start_time) * 1000,
                source_info=source_info,
            )

    def _parse_workflow_data(self, data: Dict[str, Any], source: str, start_time: float) -> ParsedWorkflowResult:
        """Parse and validate workflow data."""
        validation_result = ValidationResult(valid=True)

        try:
            # Step 1: Basic structure validation
            basic_validation = self._validate_basic_structure(data)
            validation_result.errors.extend(basic_validation.errors)
            validation_result.warnings.extend(basic_validation.warnings)

            if not basic_validation.valid and self.strict_validation:
                return self._create_result_from_validation(
                    None, validation_result, start_time, source
                )

            # Step 2: Create WorkflowDefinition (Pydantic validation)
            try:
                workflow = WorkflowDefinition(**data)
            except PydanticValidationError as e:
                for error in e.errors():
                    field_path = " -> ".join(str(loc) for loc in error["loc"])
                    validation_result.add_error(
                        field=field_path,
                        message=error["msg"],
                        value=error.get("input"),
                    )

                if self.strict_validation:
                    return self._create_result_from_validation(
                        None, validation_result, start_time, source
                    )

            # Step 3: Advanced validations (if not in performance mode)
            if not self.performance_mode:
                # Node configuration validation
                node_validation = self._validate_node_configurations(workflow)
                validation_result.errors.extend(node_validation.errors)
                validation_result.warnings.extend(node_validation.warnings)

                # Template variable validation
                if self.validate_templates:
                    template_validation = self._validate_template_variables(workflow)
                    validation_result.errors.extend(template_validation.errors)
                    validation_result.warnings.extend(template_validation.warnings)

                # Execution order validation
                order_validation = self._validate_execution_order(workflow)
                validation_result.errors.extend(order_validation.errors)
                validation_result.warnings.extend(order_validation.warnings)

            # Step 4: Create final result
            is_valid = len(validation_result.errors) == 0
            validation_result.valid = is_valid

            return self._create_result_from_validation(
                workflow if is_valid else None, validation_result, start_time, source
            )

        except Exception as e:
            return self._create_error_result(
                f"Unexpected error during parsing: {str(e)}",
                parse_time_ms=(time.time() - start_time) * 1000,
                source_info={"source": source},
            )

    # ========================================================================
    # VALIDATION METHODS
    # ========================================================================

    def _validate_basic_structure(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate basic workflow structure."""
        result = ValidationResult(valid=True)

        # Check required top-level fields
        required_fields = ["id", "name", "nodes"]
        for field in required_fields:
            if field not in data:
                result.add_error(field, f"Required field '{field}' is missing")

        # Check nodes is a list
        if "nodes" in data:
            if not isinstance(data["nodes"], list):
                result.add_error("nodes", "Field 'nodes' must be a list")
            elif len(data["nodes"]) == 0:
                result.add_error("nodes", "Workflow must have at least one node")

        return result

    def _validate_node_configurations(self, workflow: WorkflowDefinition) -> ValidationResult:
        """Validate node-specific configurations."""
        result = ValidationResult(valid=True)

        for node in workflow.nodes:
            try:
                # Get the appropriate config class for this node type
                config_class = self.node_config_classes.get(node.type)
                if config_class:
                    # Validate the node configuration
                    config_class(**node.config)
                else:
                    result.add_warning(f"Unknown node type '{node.type}' in node '{node.id}'")

            except PydanticValidationError as e:
                for error in e.errors():
                    field_path = f"nodes.{node.id}.config." + " -> ".join(str(loc) for loc in error["loc"])
                    result.add_error(
                        field=field_path,
                        message=error["msg"],
                        value=error.get("input"),
                        node_id=node.id,
                    )
            except Exception as e:
                result.add_error(
                    field=f"nodes.{node.id}.config",
                    message=f"Configuration validation error: {str(e)}",
                    node_id=node.id,
                )

        return result

    def _validate_template_variables(self, workflow: WorkflowDefinition) -> ValidationResult:
        """Validate template variable references."""
        result = ValidationResult(valid=True)

        # Get all node IDs for reference validation
        node_ids = {node.id for node in workflow.nodes}
        
        # Get all node aliases for reference validation
        node_aliases = {getattr(node, 'alias', None) for node in workflow.nodes if hasattr(node, 'alias') and getattr(node, 'alias')}
        node_aliases.discard(None)  # Remove None values

        for node in workflow.nodes:
            # Extract template variables from node config
            template_vars = self._extract_template_variables(node.config)

            for var_path in template_vars:
                validation_error = self._validate_template_variable(var_path, node.id, node_ids, node_aliases)
                if validation_error:
                    result.add_error(
                        field=f"nodes.{node.id}.config",
                        message=validation_error,
                        value=var_path,
                        node_id=node.id,
                    )

        return result

    def _validate_execution_order(self, workflow: WorkflowDefinition) -> ValidationResult:
        """Validate that template variables reference only upstream nodes."""
        result = ValidationResult(valid=True)

        # Build dependency graph for topological analysis
        dependency_graph = self._build_dependency_graph(workflow)

        for node in workflow.nodes:
            # Get all node references in this node's config
            template_vars = self._extract_template_variables(node.config)
            node_references = [
                var.split(".")[1] for var in template_vars
                if var.startswith("nodes.") and "." in var
            ]

            for referenced_node_id in node_references:
                if referenced_node_id == node.id:
                    result.add_error(
                        field=f"nodes.{node.id}",
                        message="Node cannot reference its own output",
                        node_id=node.id,
                    )
                elif not self._is_upstream_node(referenced_node_id, node.id, dependency_graph):
                    result.add_error(
                        field=f"nodes.{node.id}",
                        message=f"Node references '{referenced_node_id}' which is not upstream in execution order",
                        node_id=node.id,
                    )

        return result

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _extract_template_variables(self, config: Dict[str, Any]) -> Set[str]:
        """Extract all template variables from configuration."""
        variables = set()

        def extract_from_value(value):
            if isinstance(value, str):
                matches = self.template_pattern.findall(value)
                variables.update(matches)
            elif isinstance(value, dict):
                for v in value.values():
                    extract_from_value(v)
            elif isinstance(value, list):
                for item in value:
                    extract_from_value(item)

        extract_from_value(config)
        return variables

    def _validate_template_variable(self, var_path: str, node_id: str, node_ids: Set[str], node_aliases: Set[str] = None) -> Optional[str]:
        """Validate a single template variable path."""
        parts = var_path.split(".")
        
        if node_aliases is None:
            node_aliases = set()

        if len(parts) < 2:
            return f"Invalid template variable format: '{var_path}'"

        namespace = parts[0]

        if namespace == "workflow":
            # Validate workflow variables
            if len(parts) < 2:
                return f"Incomplete workflow variable: '{var_path}'"
            
            # Include node aliases as valid workflow variables
            valid_workflow_vars = {"id", "input", "metadata", "nodes"} | node_aliases
            if parts[1] not in valid_workflow_vars:
                return f"Unknown workflow variable: '{parts[1]}'"
            
            # If it's an alias reference (workflow.{alias}.{field})
            if parts[1] in node_aliases and len(parts) >= 2:
                # Allow any field access on aliases as they represent runtime node outputs
                # Examples: workflow.weather_agent.temperature, workflow.weather_agent.city
                # These will be resolved at runtime to the actual node output paths
                pass  # Allow all alias-based field access
            
            # Additional validation for nodes references
            elif parts[1] == "nodes" and len(parts) >= 4:
                # Format: workflow.nodes.{node_id}.{field}[.subfield]
                referenced_node = parts[2]
                if referenced_node not in node_ids:
                    return f"Referenced node '{referenced_node}' does not exist"
                
                valid_node_fields = ["output", "status", "input", "execution_time_ms", "started_at"]
                if parts[3] not in valid_node_fields:
                    return f"Unknown node field: '{parts[3]}'"

        elif namespace == "nodes":
            # Validate node references
            if len(parts) < 3:
                return f"Incomplete node reference: '{var_path}'"

            referenced_node = parts[1]
            if referenced_node not in node_ids:
                return f"Referenced node '{referenced_node}' does not exist"

            valid_node_fields = ["output", "status", "input", "execution_time_ms", "started_at"]
            if parts[2] not in valid_node_fields:
                return f"Unknown node field: '{parts[2]}'"

        elif namespace == "runtime":
            # Validate runtime variables
            if len(parts) < 2:
                return f"Incomplete runtime variable: '{var_path}'"
            valid_runtime_vars = ["timestamp", "execution_id", "current_node"]
            if parts[1] not in valid_runtime_vars:
                return f"Unknown runtime variable: '{parts[1]}'"

        else:
            return f"Unknown variable namespace: '{namespace}'"

        return None

    def _build_dependency_graph(self, workflow: WorkflowDefinition) -> Dict[str, Set[str]]:
        """Build dependency graph for topological analysis."""
        graph = {node.id: set(node.dependencies) for node in workflow.nodes}
        return graph

    def _is_upstream_node(self, target_node: str, current_node: str, graph: Dict[str, Set[str]]) -> bool:
        """Check if target_node is upstream of current_node using BFS."""
        if target_node == current_node:
            return False

        visited = set()
        queue = [current_node]
        visited.add(current_node)

        while queue:
            node = queue.pop(0)
            dependencies = graph.get(node, set())

            if target_node in dependencies:
                return True

            for dep in dependencies:
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)

        return False

    def _create_error_result(
        self,
        error_message: str,
        parse_time_ms: float,
        source_info: Optional[Dict[str, Any]] = None
    ) -> ParsedWorkflowResult:
        """Create a failed parsing result with error."""
        validation_result = ValidationResult(valid=False)
        validation_result.add_error("parse", error_message)

        return ParsedWorkflowResult(
            workflow=None,
            validation_result=validation_result,
            is_valid=False,
            parse_time_ms=parse_time_ms,
            source_info=source_info or {},
        )

    def _create_result_from_validation(
        self,
        workflow: Optional[WorkflowDefinition],
        validation_result: ValidationResult,
        start_time: float,
        source: str,
    ) -> ParsedWorkflowResult:
        """Create parsing result from validation outcome."""
        parse_time_ms = (time.time() - start_time) * 1000
        validation_result.validation_time_ms = parse_time_ms

        if workflow:
            validation_result.node_count = len(workflow.nodes)

        return ParsedWorkflowResult(
            workflow=workflow,
            validation_result=validation_result,
            is_valid=validation_result.valid,
            parse_time_ms=parse_time_ms,
            source_info={"source": source},
        )


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def validate_workflow_file(file_path: Union[str, Path]) -> ParsedWorkflowResult:
    """Convenience function to validate a workflow file."""
    parser = WorkflowDefinitionParser()
    return parser.parse_file(file_path)


def validate_workflow_dict(workflow_data: Dict[str, Any]) -> ParsedWorkflowResult:
    """Convenience function to validate a workflow dictionary."""
    parser = WorkflowDefinitionParser()
    return parser.parse_dict(workflow_data)