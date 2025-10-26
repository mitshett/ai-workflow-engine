"""
Workflow Validator - Comprehensive workflow validation focused on termination analysis.

This module provides workflow validation including:
- End node validation with reachability analysis
- Structure validation and node reference checking
- Performance-optimized validation with caching
- Comprehensive error reporting for UI integration

Note: Cycle detection has been removed to allow legitimate retry/polling patterns.
Users are responsible for ensuring loops have proper safeguards (timeouts, max iterations).

Author: AI Workflow Engine Team
"""

from typing import Dict, List, Set, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict
import hashlib
import json
import time
from datetime import datetime


@dataclass
class TerminationIssue:
    """Represents a termination validation issue."""
    issue_type: str  # "no_terminals", "dangling_branch", "unreachable_terminal", "missing_next"
    message: str
    node_id: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class TerminationResult:
    """Result of end node validation analysis."""
    is_valid: bool
    terminal_nodes: List[str]
    issues: List[TerminationIssue]
    nodes_without_path_to_end: List[str]
    unreachable_terminals: List[str]
    execution_time_ms: float


@dataclass
class ValidationError:
    """Comprehensive validation error with context."""
    error_type: str
    message: str
    node_id: Optional[str] = None
    severity: str = "error"  # "error", "warning", "info"
    suggestion: Optional[str] = None
    details: Optional[str] = None


@dataclass
class WorkflowValidationResult:
    """Complete workflow validation result."""
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]

    # Termination-specific details
    terminal_nodes: List[str]
    nodes_without_path_to_end: List[str]

    # Performance metrics
    node_count: int
    max_parallel_nodes: int
    optimization_suggestions: List[str]
    validation_time_ms: float

    # Optional fields (with defaults) must come last
    estimated_execution_time_seconds: Optional[int] = None
    estimated_memory_usage_mb: Optional[int] = None


class TerminationValidator:
    """
    Validates proper workflow termination using reachability analysis.

    Ensures that:
    1. All workflow branches have clear termination points
    2. All nodes can reach at least one terminal node
    3. No dangling branches exist
    4. Terminal nodes are reachable from workflow start
    """

    def __init__(self):
        self.reverse_graph: Dict[str, List[str]] = {}

    def validate_termination(self, graph: Dict[str, List[str]], workflow_definition: dict) -> TerminationResult:
        """
        Comprehensive termination validation.

        Args:
            graph: Adjacency list representation of workflow
            workflow_definition: Original workflow definition for detailed analysis

        Returns:
            TerminationResult with validation details and issues
        """
        start_time = time.time()
        issues = []

        # 1. Find all terminal nodes (nodes with no outgoing connections)
        terminal_nodes = self._find_terminal_nodes(graph)
        if not terminal_nodes:
            issues.append(TerminationIssue(
                issue_type="no_terminals",
                message="Workflow has no terminal nodes - execution will never complete",
                suggestion="Add at least one node with empty 'next' array"
            ))

        # 2. Check for nodes missing 'next' field entirely
        dangling_nodes = self._find_nodes_missing_next_field(workflow_definition)
        for node_id in dangling_nodes:
            issues.append(TerminationIssue(
                issue_type="missing_next",
                message=f"Node '{node_id}' missing 'next' field - unclear termination",
                node_id=node_id,
                suggestion=f"Add 'next': [] to node '{node_id}' or connect it to other nodes"
            ))

        # 3. Find nodes that cannot reach any terminal node
        nodes_without_path_to_end = []
        if terminal_nodes:
            nodes_without_path_to_end = self._find_nodes_without_path_to_terminals(graph, terminal_nodes)
            for node_id in nodes_without_path_to_end:
                issues.append(TerminationIssue(
                    issue_type="dangling_branch",
                    message=f"Node '{node_id}' has no path to any terminal node",
                    node_id=node_id,
                    suggestion=f"Connect '{node_id}' to the main workflow path or add termination"
                ))

        # 4. Find unreachable terminal nodes
        start_nodes = self._find_start_nodes(graph)
        unreachable_terminals = []
        if terminal_nodes and start_nodes:
            unreachable_terminals = self._find_unreachable_terminals(graph, start_nodes, terminal_nodes)
            for node_id in unreachable_terminals:
                issues.append(TerminationIssue(
                    issue_type="unreachable_terminal",
                    message=f"Terminal node '{node_id}' cannot be reached from workflow start",
                    node_id=node_id,
                    suggestion=f"Connect '{node_id}' to the main workflow or remove it"
                ))

        execution_time = (time.time() - start_time) * 1000

        return TerminationResult(
            is_valid=len(issues) == 0,
            terminal_nodes=terminal_nodes,
            issues=issues,
            nodes_without_path_to_end=nodes_without_path_to_end,
            unreachable_terminals=unreachable_terminals,
            execution_time_ms=execution_time
        )

    def _find_terminal_nodes(self, graph: Dict[str, List[str]]) -> List[str]:
        """Find nodes with no outgoing connections."""
        return [node for node, connections in graph.items() if not connections]

    def _find_nodes_missing_next_field(self, workflow_definition: dict) -> List[str]:
        """Find nodes that don't have a 'next' field at all."""
        missing_next = []
        for node in workflow_definition.get('nodes', []):
            if 'next' not in node:
                missing_next.append(node['id'])
        return missing_next

    def _find_nodes_without_path_to_terminals(self, graph: Dict[str, List[str]], terminals: List[str]) -> List[str]:
        """Use reverse DFS to find nodes that can't reach any terminal."""
        if not terminals:
            return list(graph.keys())

        # Build reverse graph
        reverse_graph = self._build_reverse_graph(graph)

        # DFS backwards from all terminals to find reachable nodes
        reachable = set()
        for terminal in terminals:
            self._dfs_mark_reachable(terminal, reverse_graph, reachable)

        # Return nodes not reachable from any terminal
        all_nodes = set(graph.keys())
        return list(all_nodes - reachable)

    def _find_start_nodes(self, graph: Dict[str, List[str]]) -> List[str]:
        """Find nodes with no incoming connections (potential start nodes)."""
        has_incoming = set()
        for node, connections in graph.items():
            for target in connections:
                has_incoming.add(target)

        all_nodes = set(graph.keys())
        return list(all_nodes - has_incoming)

    def _find_unreachable_terminals(self, graph: Dict[str, List[str]], start_nodes: List[str], terminals: List[str]) -> List[str]:
        """Find terminal nodes that can't be reached from any start node."""
        if not start_nodes:
            return terminals

        # DFS forward from all start nodes
        reachable = set()
        for start in start_nodes:
            self._dfs_mark_reachable_forward(start, graph, reachable)

        # Return terminals not reachable from start
        return [terminal for terminal in terminals if terminal not in reachable]

    def _build_reverse_graph(self, graph: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Build reverse graph for backward reachability analysis."""
        reverse_graph = defaultdict(list)
        for node, connections in graph.items():
            for target in connections:
                reverse_graph[target].append(node)
        return dict(reverse_graph)

    def _dfs_mark_reachable(self, node: str, reverse_graph: Dict[str, List[str]], reachable: Set[str]) -> None:
        """Mark all nodes reachable via reverse DFS."""
        if node in reachable:
            return

        reachable.add(node)
        for parent in reverse_graph.get(node, []):
            self._dfs_mark_reachable(parent, reverse_graph, reachable)

    def _dfs_mark_reachable_forward(self, node: str, graph: Dict[str, List[str]], reachable: Set[str]) -> None:
        """Mark all nodes reachable via forward DFS."""
        if node in reachable:
            return

        reachable.add(node)
        for child in graph.get(node, []):
            self._dfs_mark_reachable_forward(child, graph, reachable)


class ComprehensiveWorkflowValidator:
    """
    Main validator class that orchestrates all workflow validation.

    Provides comprehensive validation including:
    - Structural validation
    - Termination analysis
    - Performance estimation
    - Optimization suggestions

    Note: Cycle detection removed to allow legitimate retry/polling patterns.
    """

    def __init__(self):
        self.termination_validator = TerminationValidator()
        self._graph_cache: Dict[str, Dict[str, List[str]]] = {}

    def validate_workflow(self, workflow_definition: dict) -> WorkflowValidationResult:
        """
        Comprehensive workflow validation.

        Args:
            workflow_definition: Complete workflow definition dictionary

        Returns:
            WorkflowValidationResult with all validation details
        """
        start_time = time.time()
        errors = []
        warnings = []
        optimization_suggestions = []

        # 1. Basic structure validation
        structure_issues = self._validate_basic_structure(workflow_definition)
        errors.extend(structure_issues)

        if errors:
            # Don't continue if basic structure is invalid
            return self._create_invalid_result(errors, time.time() - start_time)

        # 2. Build graph representation (cached for performance)
        graph = self._build_graph_cached(workflow_definition)
        node_count = len(graph)

        # 3. Termination validation (check for proper end nodes)
        termination_result = self.termination_validator.validate_termination(graph, workflow_definition)

        for issue in termination_result.issues:
            errors.append(ValidationError(
                error_type=issue.issue_type,
                message=issue.message,
                node_id=issue.node_id,
                severity="error",
                suggestion=issue.suggestion
            ))

        # 4. Performance analysis and optimization suggestions
        max_parallel_nodes = self._analyze_parallelism(graph)
        estimated_time, estimated_memory = self._estimate_resource_usage(workflow_definition, node_count)
        optimization_suggestions = self._generate_optimization_suggestions(graph, workflow_definition)

        # 5. Performance warnings
        if node_count > 50:
            warnings.append(ValidationError(
                error_type="performance_warning",
                message=f"Workflow has {node_count} nodes which may impact execution time",
                severity="warning",
                suggestion="Consider breaking into smaller sub-workflows"
            ))

        validation_time = (time.time() - start_time) * 1000

        return WorkflowValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            terminal_nodes=termination_result.terminal_nodes,
            nodes_without_path_to_end=termination_result.nodes_without_path_to_end,
            node_count=node_count,
            max_parallel_nodes=max_parallel_nodes,
            estimated_execution_time_seconds=estimated_time,
            estimated_memory_usage_mb=estimated_memory,
            optimization_suggestions=optimization_suggestions,
            validation_time_ms=validation_time
        )

    def _validate_basic_structure(self, workflow_definition: dict) -> List[ValidationError]:
        """Validate basic workflow structure and format."""
        errors = []

        if not isinstance(workflow_definition, dict):
            errors.append(ValidationError(
                error_type="invalid_format",
                message="Workflow definition must be a dictionary",
                severity="error"
            ))
            return errors

        if 'nodes' not in workflow_definition:
            errors.append(ValidationError(
                error_type="missing_nodes",
                message="Workflow definition missing 'nodes' field",
                severity="error"
            ))
            return errors

        nodes = workflow_definition['nodes']
        if not isinstance(nodes, list) or not nodes:
            errors.append(ValidationError(
                error_type="invalid_nodes",
                message="Workflow 'nodes' must be a non-empty list",
                severity="error"
            ))
            return errors

        # Validate individual nodes
        node_ids = set()
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(ValidationError(
                    error_type="invalid_node",
                    message=f"Node {i} must be a dictionary",
                    severity="error"
                ))
                continue

            if 'id' not in node:
                errors.append(ValidationError(
                    error_type="missing_node_id",
                    message=f"Node {i} missing required 'id' field",
                    severity="error"
                ))
                continue

            node_id = node['id']
            if node_id in node_ids:
                errors.append(ValidationError(
                    error_type="duplicate_node_id",
                    message=f"Duplicate node ID: '{node_id}'",
                    node_id=node_id,
                    severity="error"
                ))

            node_ids.add(node_id)

        return errors

    def _build_graph_cached(self, workflow_definition: dict) -> Dict[str, List[str]]:
        """Build graph representation with caching for performance."""
        # Create cache key from workflow definition
        workflow_str = json.dumps(workflow_definition, sort_keys=True)
        cache_key = hashlib.md5(workflow_str.encode()).hexdigest()

        if cache_key in self._graph_cache:
            return self._graph_cache[cache_key]

        graph = self._build_graph(workflow_definition)
        self._graph_cache[cache_key] = graph

        # Limit cache size to prevent memory issues
        if len(self._graph_cache) > 100:
            oldest_key = next(iter(self._graph_cache))
            del self._graph_cache[oldest_key]

        return graph

    def _build_graph(self, workflow_definition: dict) -> Dict[str, List[str]]:
        """Build adjacency list representation of workflow graph."""
        graph = {}
        all_node_ids = set()

        # First pass: collect all node IDs
        for node in workflow_definition.get('nodes', []):
            node_id = node.get('id')
            if node_id:
                all_node_ids.add(node_id)

        # Second pass: build graph and validate references
        for node in workflow_definition.get('nodes', []):
            node_id = node.get('id')
            if node_id:
                next_nodes = node.get('next', [])
                if isinstance(next_nodes, list):
                    # Validate that all referenced nodes exist
                    for next_node in next_nodes:
                        if next_node not in all_node_ids:
                            raise ValueError(f"Node '{node_id}' references non-existent node '{next_node}'")
                    graph[node_id] = next_nodes
                else:
                    graph[node_id] = []

        return graph


    def _analyze_parallelism(self, graph: Dict[str, List[str]]) -> int:
        """Analyze potential parallelism in the workflow."""
        # Simple analysis: find maximum number of nodes that could run in parallel
        # This is a basic implementation - could be enhanced with topological analysis

        if not graph:
            return 0

        # Find nodes with no dependencies (can start in parallel)
        has_incoming = set()
        for node, connections in graph.items():
            for target in connections:
                has_incoming.add(target)

        start_nodes = [node for node in graph if node not in has_incoming]
        return max(1, len(start_nodes))

    def _estimate_resource_usage(self, workflow_definition: dict, node_count: int) -> Tuple[Optional[int], Optional[int]]:
        """Estimate execution time and memory usage."""
        # Basic estimation - could be enhanced with ML models or historical data

        # Estimate execution time (rough approximation)
        base_time_per_node = 5  # seconds
        estimated_time = node_count * base_time_per_node

        # Estimate memory usage (rough approximation)
        base_memory_per_node = 2  # MB
        estimated_memory = max(32, node_count * base_memory_per_node)  # Minimum 32MB

        return estimated_time, estimated_memory

    def _generate_optimization_suggestions(self, graph: Dict[str, List[str]], workflow_definition: dict) -> List[str]:
        """Generate optimization suggestions based on workflow analysis."""
        suggestions = []

        # Check for potential parallelization opportunities
        sequential_chains = self._find_sequential_chains(graph)
        if len(sequential_chains) > 3:
            suggestions.append("Consider parallelizing independent sequential chains")

        # Check for large fan-out patterns
        for node, connections in graph.items():
            if len(connections) > 5:
                suggestions.append(f"Node '{node}' has many connections - consider using sub-workflows")

        # Check for nodes that could be cached
        node_types = {}
        for node in workflow_definition.get('nodes', []):
            node_type = node.get('type', 'unknown')
            if node_type in node_types:
                node_types[node_type] += 1
            else:
                node_types[node_type] = 1

        for node_type, count in node_types.items():
            if count > 3 and node_type in ['agent', 'tool']:
                suggestions.append(f"Multiple {node_type} nodes detected - consider result caching")

        return suggestions

    def _find_sequential_chains(self, graph: Dict[str, List[str]]) -> List[List[str]]:
        """Find sequences of nodes that execute one after another."""
        chains = []
        visited = set()

        for node in graph:
            if node not in visited:
                chain = self._trace_sequential_chain(node, graph, visited)
                if len(chain) > 1:
                    chains.append(chain)

        return chains

    def _trace_sequential_chain(self, start_node: str, graph: Dict[str, List[str]], visited: Set[str]) -> List[str]:
        """Trace a sequential chain starting from a node."""
        chain = [start_node]
        visited.add(start_node)
        current = start_node

        while True:
            connections = graph.get(current, [])
            if len(connections) != 1:  # Not a simple chain
                break

            next_node = connections[0]
            if next_node in visited:  # Already processed
                break

            # Check if next_node has only one incoming connection (from current)
            incoming_count = sum(1 for node, conns in graph.items() if next_node in conns)
            if incoming_count != 1:  # Not a simple chain
                break

            chain.append(next_node)
            visited.add(next_node)
            current = next_node

        return chain

    def _create_invalid_result(self, errors: List[ValidationError], elapsed_time: float) -> WorkflowValidationResult:
        """Create a validation result for invalid workflows."""
        return WorkflowValidationResult(
            is_valid=False,
            errors=errors,
            warnings=[],
            terminal_nodes=[],
            nodes_without_path_to_end=[],
            node_count=0,
            max_parallel_nodes=0,
            optimization_suggestions=[],
            validation_time_ms=elapsed_time * 1000
        )


# Convenience function for easy usage
def validate_workflow(workflow_definition: dict) -> WorkflowValidationResult:
    """
    Convenience function for validating a workflow definition.

    Args:
        workflow_definition: Complete workflow definition dictionary

    Returns:
        WorkflowValidationResult with comprehensive validation details
    """
    validator = ComprehensiveWorkflowValidator()
    return validator.validate_workflow(workflow_definition)


# Example usage and testing functions
if __name__ == "__main__":
    # Test with a simple valid workflow
    valid_workflow = {
        "id": "test_workflow",
        "name": "Test Workflow",
        "nodes": [
            {"id": "start", "type": "agent", "next": ["process"]},
            {"id": "process", "type": "tool", "next": ["end"]},
            {"id": "end", "type": "agent", "next": []}
        ]
    }

    # Test with a workflow containing retry loops (now allowed)
    retry_workflow = {
        "id": "retry_workflow",
        "name": "Retry Workflow",
        "nodes": [
            {"id": "api_call", "type": "tool", "next": ["check_result"]},
            {"id": "check_result", "type": "condition", "next": ["api_call", "success"]},  # Loop back for retry
            {"id": "success", "type": "agent", "next": []}
        ]
    }

    print("Testing valid workflow:")
    result = validate_workflow(valid_workflow)
    print(f"Valid: {result.is_valid}")
    print(f"Errors: {len(result.errors)}")
    print(f"Terminal nodes: {result.terminal_nodes}")

    print("\nTesting retry workflow (loops now allowed):")
    result = validate_workflow(retry_workflow)
    print(f"Valid: {result.is_valid}")
    print(f"Errors: {len(result.errors)}")
    print(f"Terminal nodes: {result.terminal_nodes}")
    print("Note: Loops are now allowed for legitimate retry/polling patterns")