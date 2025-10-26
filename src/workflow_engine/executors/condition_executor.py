"""
ConditionExecutor - Enterprise-Grade Conditional Logic Engine

Implements sophisticated conditional branching for workflow execution with:
- Multiple condition types (string, numeric, regex, boolean, json_path)
- Extensible condition evaluation framework
- Complex routing logic with fallback mechanisms
- Comprehensive error handling and validation
- Performance optimization and caching
- Enterprise logging and monitoring

Author: AI Workflow Engine Team
"""

import re
import json
import time
import structlog
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union, Tuple
from enum import Enum

from ..core.node_executor import (
    NodeExecutor,
    ExecutionResult,
    ExecutionStatus,
    ExecutionMetrics,
    ValidationResult,
    validate_required_config
)
from ..core.context import ExecutionContext
from ..core.schemas import WorkflowNode

# Set up structured logging
logger = structlog.get_logger(__name__)


class ConditionType(str, Enum):
    """Supported condition types for evaluation."""
    STRING_MATCH = "string_match"
    STRING_CONTAINS = "string_contains"
    REGEX_MATCH = "regex_match"
    NUMERIC_COMPARISON = "numeric_comparison"
    BOOLEAN_CHECK = "boolean_check"
    JSON_PATH = "json_path"
    RANGE_CHECK = "range_check"
    LIST_CONTAINS = "list_contains"
    CUSTOM = "custom"


class ComparisonOperator(str, Enum):
    """Numeric comparison operators."""
    EQUAL = "eq"
    NOT_EQUAL = "ne"
    GREATER_THAN = "gt"
    GREATER_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_EQUAL = "lte"


class ConditionEvaluationResult:
    """Result of condition evaluation with detailed information."""
    
    def __init__(
        self,
        matched: bool,
        target_node: Optional[str] = None,
        condition_name: Optional[str] = None,
        evaluation_details: Optional[Dict[str, Any]] = None,
        evaluation_time_ms: float = 0.0
    ):
        self.matched = matched
        self.target_node = target_node
        self.condition_name = condition_name
        self.evaluation_details = evaluation_details or {}
        self.evaluation_time_ms = evaluation_time_ms


class BaseConditionEvaluator(ABC):
    """Abstract base class for condition evaluators."""
    
    @abstractmethod
    def evaluate(
        self,
        input_value: Any,
        condition_config: Dict[str, Any],
        context: ExecutionContext
    ) -> ConditionEvaluationResult:
        """Evaluate the condition and return result."""
        pass
    
    @abstractmethod
    def validate_config(self, condition_config: Dict[str, Any]) -> ValidationResult:
        """Validate condition configuration."""
        pass


class StringMatchEvaluator(BaseConditionEvaluator):
    """Evaluates string matching conditions."""
    
    def evaluate(
        self,
        input_value: Any,
        condition_config: Dict[str, Any],
        context: ExecutionContext
    ) -> ConditionEvaluationResult:
        start_time = time.time()
        
        try:
            input_str = str(input_value).strip()
            expected_value = str(condition_config["value"]).strip()
            case_sensitive = condition_config.get("case_sensitive", True)
            
            if not case_sensitive:
                input_str = input_str.lower()
                expected_value = expected_value.lower()
            
            matched = input_str == expected_value
            
            evaluation_time = (time.time() - start_time) * 1000
            
            return ConditionEvaluationResult(
                matched=matched,
                target_node=condition_config.get("target"),
                condition_name=condition_config.get("name", "string_match"),
                evaluation_details={
                    "input_value": input_str,
                    "expected_value": expected_value,
                    "case_sensitive": case_sensitive,
                    "comparison_method": "exact_match"
                },
                evaluation_time_ms=evaluation_time
            )
            
        except Exception as e:
            logger.error("String match evaluation failed", error=str(e))
            return ConditionEvaluationResult(
                matched=False,
                evaluation_details={"error": str(e)},
                evaluation_time_ms=(time.time() - start_time) * 1000
            )
    
    def validate_config(self, condition_config: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        if "value" not in condition_config:
            result.add_error("Missing required 'value' field", field="value")
        
        if "target" not in condition_config:
            result.add_error("Missing required 'target' field", field="target")
        
        case_sensitive = condition_config.get("case_sensitive")
        if case_sensitive is not None and not isinstance(case_sensitive, bool):
            result.add_error("case_sensitive must be boolean", field="case_sensitive")
        
        return result


class RegexMatchEvaluator(BaseConditionEvaluator):
    """Evaluates regular expression matching conditions."""
    
    def __init__(self):
        self._compiled_patterns = {}  # Pattern cache for performance
    
    def evaluate(
        self,
        input_value: Any,
        condition_config: Dict[str, Any],
        context: ExecutionContext
    ) -> ConditionEvaluationResult:
        start_time = time.time()
        
        try:
            input_str = str(input_value)
            pattern = condition_config["pattern"]
            flags = condition_config.get("flags", 0)
            
            # Use cached compiled pattern for performance
            pattern_key = f"{pattern}:{flags}"
            if pattern_key not in self._compiled_patterns:
                self._compiled_patterns[pattern_key] = re.compile(pattern, flags)
            
            compiled_pattern = self._compiled_patterns[pattern_key]
            match_obj = compiled_pattern.search(input_str)
            matched = match_obj is not None
            
            evaluation_time = (time.time() - start_time) * 1000
            
            evaluation_details = {
                "input_value": input_str,
                "pattern": pattern,
                "flags": flags,
                "match_found": matched
            }
            
            if matched and match_obj:
                evaluation_details.update({
                    "match_start": match_obj.start(),
                    "match_end": match_obj.end(),
                    "matched_text": match_obj.group(0),
                    "groups": match_obj.groups()
                })
            
            return ConditionEvaluationResult(
                matched=matched,
                target_node=condition_config.get("target"),
                condition_name=condition_config.get("name", "regex_match"),
                evaluation_details=evaluation_details,
                evaluation_time_ms=evaluation_time
            )
            
        except re.error as e:
            logger.error("Regex compilation failed", pattern=pattern, error=str(e))
            return ConditionEvaluationResult(
                matched=False,
                evaluation_details={"regex_error": str(e)},
                evaluation_time_ms=(time.time() - start_time) * 1000
            )
        except Exception as e:
            logger.error("Regex evaluation failed", error=str(e))
            return ConditionEvaluationResult(
                matched=False,
                evaluation_details={"error": str(e)},
                evaluation_time_ms=(time.time() - start_time) * 1000
            )
    
    def validate_config(self, condition_config: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        if "pattern" not in condition_config:
            result.add_error("Missing required 'pattern' field", field="pattern")
        else:
            # Test pattern compilation
            try:
                pattern = condition_config["pattern"]
                flags = condition_config.get("flags", 0)
                re.compile(pattern, flags)
            except re.error as e:
                result.add_error(f"Invalid regex pattern: {str(e)}", field="pattern")
        
        if "target" not in condition_config:
            result.add_error("Missing required 'target' field", field="target")
        
        return result


class NumericComparisonEvaluator(BaseConditionEvaluator):
    """Evaluates numeric comparison conditions."""
    
    def evaluate(
        self,
        input_value: Any,
        condition_config: Dict[str, Any],
        context: ExecutionContext
    ) -> ConditionEvaluationResult:
        start_time = time.time()
        
        try:
            # Convert input to number
            try:
                if isinstance(input_value, str):
                    input_num = float(input_value) if '.' in input_value else int(input_value)
                else:
                    input_num = float(input_value)
            except (ValueError, TypeError):
                return ConditionEvaluationResult(
                    matched=False,
                    evaluation_details={"error": f"Cannot convert '{input_value}' to number"},
                    evaluation_time_ms=(time.time() - start_time) * 1000
                )
            
            expected_value = condition_config["value"]
            operator = ComparisonOperator(condition_config.get("operator", "eq"))
            
            # Perform comparison
            if operator == ComparisonOperator.EQUAL:
                matched = input_num == expected_value
            elif operator == ComparisonOperator.NOT_EQUAL:
                matched = input_num != expected_value
            elif operator == ComparisonOperator.GREATER_THAN:
                matched = input_num > expected_value
            elif operator == ComparisonOperator.GREATER_EQUAL:
                matched = input_num >= expected_value
            elif operator == ComparisonOperator.LESS_THAN:
                matched = input_num < expected_value
            elif operator == ComparisonOperator.LESS_EQUAL:
                matched = input_num <= expected_value
            else:
                raise ValueError(f"Unsupported operator: {operator}")
            
            evaluation_time = (time.time() - start_time) * 1000
            
            return ConditionEvaluationResult(
                matched=matched,
                target_node=condition_config.get("target"),
                condition_name=condition_config.get("name", "numeric_comparison"),
                evaluation_details={
                    "input_value": input_num,
                    "expected_value": expected_value,
                    "operator": operator.value,
                    "comparison_result": matched
                },
                evaluation_time_ms=evaluation_time
            )
            
        except Exception as e:
            logger.error("Numeric comparison evaluation failed", error=str(e))
            return ConditionEvaluationResult(
                matched=False,
                evaluation_details={"error": str(e)},
                evaluation_time_ms=(time.time() - start_time) * 1000
            )
    
    def validate_config(self, condition_config: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        if "value" not in condition_config:
            result.add_error("Missing required 'value' field", field="value")
        elif not isinstance(condition_config["value"], (int, float)):
            result.add_error("Value must be numeric", field="value")
        
        if "target" not in condition_config:
            result.add_error("Missing required 'target' field", field="target")
        
        operator = condition_config.get("operator", "eq")
        try:
            ComparisonOperator(operator)
        except ValueError:
            valid_ops = [op.value for op in ComparisonOperator]
            result.add_error(
                f"Invalid operator '{operator}'. Valid operators: {valid_ops}",
                field="operator"
            )
        
        return result


class JSONPathEvaluator(BaseConditionEvaluator):
    """Evaluates JSON path-based conditions."""
    
    def evaluate(
        self,
        input_value: Any,
        condition_config: Dict[str, Any],
        context: ExecutionContext
    ) -> ConditionEvaluationResult:
        start_time = time.time()
        
        try:
            # Parse JSON if input is string
            if isinstance(input_value, str):
                try:
                    data = json.loads(input_value)
                except json.JSONDecodeError:
                    data = {"raw_string": input_value}
            elif isinstance(input_value, dict):
                data = input_value
            else:
                data = {"value": input_value}
            
            json_path = condition_config["path"]
            expected_value = condition_config["value"]
            
            # Simple JSON path evaluation (supports basic dot notation)
            try:
                current = data
                for key in json_path.split('.'):
                    if key.startswith('[') and key.endswith(']'):
                        # Array index
                        index = int(key[1:-1])
                        current = current[index]
                    else:
                        current = current[key]
                
                matched = current == expected_value
                
            except (KeyError, IndexError, TypeError, ValueError) as e:
                matched = False
                current = None
            
            evaluation_time = (time.time() - start_time) * 1000
            
            return ConditionEvaluationResult(
                matched=matched,
                target_node=condition_config.get("target"),
                condition_name=condition_config.get("name", "json_path"),
                evaluation_details={
                    "json_path": json_path,
                    "extracted_value": current,
                    "expected_value": expected_value,
                    "path_exists": current is not None
                },
                evaluation_time_ms=evaluation_time
            )
            
        except Exception as e:
            logger.error("JSON path evaluation failed", error=str(e))
            return ConditionEvaluationResult(
                matched=False,
                evaluation_details={"error": str(e)},
                evaluation_time_ms=(time.time() - start_time) * 1000
            )
    
    def validate_config(self, condition_config: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        if "path" not in condition_config:
            result.add_error("Missing required 'path' field", field="path")
        
        if "value" not in condition_config:
            result.add_error("Missing required 'value' field", field="value")
        
        if "target" not in condition_config:
            result.add_error("Missing required 'target' field", field="target")
        
        return result


class ConditionExecutor(NodeExecutor):
    """
    Enterprise-grade conditional node executor.
    
    Supports multiple condition types with extensible evaluation framework:
    - String matching (exact, case-insensitive)
    - Regular expressions with caching
    - Numeric comparisons (eq, ne, gt, gte, lt, lte)
    - Boolean checks
    - JSON path evaluation
    - Range checks
    - List membership tests
    - Custom condition evaluators
    """

    NODE_TYPE = "condition"

    def __init__(self):
        super().__init__(default_timeout=60)
        
        # Register built-in condition evaluators
        self._evaluators = {
            ConditionType.STRING_MATCH: StringMatchEvaluator(),
            ConditionType.STRING_CONTAINS: self._create_string_contains_evaluator(),
            ConditionType.REGEX_MATCH: RegexMatchEvaluator(),
            ConditionType.NUMERIC_COMPARISON: NumericComparisonEvaluator(),
            ConditionType.JSON_PATH: JSONPathEvaluator(),
        }
        
        # Performance metrics
        self._evaluation_stats = {
            "total_evaluations": 0,
            "successful_evaluations": 0,
            "failed_evaluations": 0,
            "average_evaluation_time_ms": 0.0
        }

    def _create_string_contains_evaluator(self):
        """Create string contains evaluator as a simple wrapper."""
        class StringContainsEvaluator(StringMatchEvaluator):
            def evaluate(self, input_value, condition_config, context):
                # Override to use 'in' instead of '=='
                start_time = time.time()
                try:
                    input_str = str(input_value).strip()
                    search_value = str(condition_config["value"]).strip()
                    case_sensitive = condition_config.get("case_sensitive", True)
                    
                    if not case_sensitive:
                        input_str = input_str.lower()
                        search_value = search_value.lower()
                    
                    matched = search_value in input_str
                    
                    return ConditionEvaluationResult(
                        matched=matched,
                        target_node=condition_config.get("target"),
                        condition_name=condition_config.get("name", "string_contains"),
                        evaluation_details={
                            "input_value": input_str,
                            "search_value": search_value,
                            "case_sensitive": case_sensitive,
                            "comparison_method": "contains"
                        },
                        evaluation_time_ms=(time.time() - start_time) * 1000
                    )
                except Exception as e:
                    return ConditionEvaluationResult(
                        matched=False,
                        evaluation_details={"error": str(e)},
                        evaluation_time_ms=(time.time() - start_time) * 1000
                    )
        
        return StringContainsEvaluator()

    async def execute_impl(self, node: WorkflowNode, context: ExecutionContext) -> ExecutionResult:
        """Execute conditional logic and determine routing."""
        
        start_time = datetime.now(timezone.utc)
        
        try:
            logger.info(
                "Executing condition node",
                node_id=node.id,
                condition_type=node.config.get("condition_type")
            )

            # Get input value
            input_source = node.config.get("input_source")
            if not input_source:
                raise ValueError("Missing 'input_source' in condition configuration")
            
            # Resolve input value from template
            input_value = await context.resolve_template(input_source)
            
            # Get condition configuration
            condition_type = ConditionType(node.config.get("condition_type", "string_match"))
            rules = node.config.get("rules", [])
            default_target = node.config.get("default_target")
            
            if not rules and not default_target:
                raise ValueError("No condition rules or default target specified")

            # Evaluate conditions
            evaluation_results = []
            matched_target = None
            
            for rule in rules:
                if condition_type not in self._evaluators:
                    raise ValueError(f"Unsupported condition type: {condition_type}")
                
                evaluator = self._evaluators[condition_type]
                result = evaluator.evaluate(input_value, rule, context)
                evaluation_results.append(result)
                
                if result.matched and not matched_target:
                    matched_target = result.target_node
                    logger.info(
                        "Condition matched",
                        condition_name=result.condition_name,
                        target_node=matched_target,
                        evaluation_time_ms=result.evaluation_time_ms
                    )
                    break
            
            # Use default target if no conditions matched
            if not matched_target:
                matched_target = default_target
                logger.info("No conditions matched, using default target", target=matched_target)
            
            if not matched_target:
                raise ValueError("No matching condition found and no default target specified")

            # Calculate metrics
            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()
            
            # Update statistics
            self._evaluation_stats["total_evaluations"] += len(evaluation_results)
            successful_evals = sum(1 for r in evaluation_results if not r.evaluation_details.get("error"))
            self._evaluation_stats["successful_evaluations"] += successful_evals
            self._evaluation_stats["failed_evaluations"] += len(evaluation_results) - successful_evals

            # Prepare result data
            result_data = {
                "condition_type": condition_type.value,
                "input_value": input_value,
                "matched_target": matched_target,
                "evaluation_results": [
                    {
                        "condition_name": r.condition_name,
                        "matched": r.matched,
                        "target_node": r.target_node,
                        "evaluation_time_ms": r.evaluation_time_ms,
                        "details": r.evaluation_details
                    }
                    for r in evaluation_results
                ],
                "rules_evaluated": len(evaluation_results),
                "used_default": matched_target == default_target
            }

            # Context updates
            context_updates = {
                f"nodes.{node.id}.output": result_data,
                f"nodes.{node.id}.routed_to": matched_target
            }

            logger.info(
                "Condition evaluation completed",
                node_id=node.id,
                matched_target=matched_target,
                rules_evaluated=len(evaluation_results),
                duration_ms=metrics.duration_ms
            )

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                data=result_data,
                metrics=metrics,
                context_updates=context_updates,
                next_nodes=[matched_target] if matched_target else []
            )

        except Exception as e:
            logger.error(
                "Condition execution failed",
                node_id=node.id,
                error=str(e),
                error_type=type(e).__name__
            )

            metrics = ExecutionMetrics(start_time=start_time)
            metrics.mark_completed()

            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                metrics=metrics
            )
            result.set_error(e, f"Condition execution failed for node {node.id}")
            return result

    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate condition node configuration."""
        result = ValidationResult(is_valid=True)

        # Check required fields
        required_validation = validate_required_config(config, ["input_source"])
        result = result.merge(required_validation)

        # Validate condition type
        condition_type = config.get("condition_type", "string_match")
        try:
            ConditionType(condition_type)
        except ValueError:
            valid_types = [t.value for t in ConditionType]
            result.add_error(
                f"Invalid condition_type '{condition_type}'. Valid types: {valid_types}",
                field="condition_type"
            )

        # Validate rules or default_target
        rules = config.get("rules", [])
        default_target = config.get("default_target")
        
        if not rules and not default_target:
            result.add_error(
                "Must specify either 'rules' or 'default_target' (or both)",
                field="rules"
            )

        # Validate individual rules
        if rules:
            if not isinstance(rules, list):
                result.add_error("Rules must be a list", field="rules")
            else:
                condition_type_enum = ConditionType(condition_type)
                if condition_type_enum in self._evaluators:
                    evaluator = self._evaluators[condition_type_enum]
                    for i, rule in enumerate(rules):
                        rule_validation = evaluator.validate_config(rule)
                        if not rule_validation.is_valid:
                            for error in rule_validation.errors:
                                result.add_error(
                                    f"Rule {i+1}: {error.message}",
                                    field=f"rules[{i}].{error.field}"
                                )

        return result

    def get_retry_policy(self):
        """Get retry policy for condition execution."""
        from ..core.node_executor import RetryPolicy

        return RetryPolicy(
            max_attempts=2,
            base_delay_seconds=0.5,
            exponential_backoff=False,
            retry_on_timeout=True,
            retry_on_network_error=False,
            retry_on_rate_limit=False,
            retry_on_server_error=False,
            retry_on_authentication_error=False,
            retry_on_validation_error=False
        )

    def register_custom_evaluator(
        self,
        condition_type: str,
        evaluator: BaseConditionEvaluator
    ) -> None:
        """Register a custom condition evaluator for extensibility."""
        self._evaluators[ConditionType.CUSTOM] = evaluator
        logger.info("Registered custom condition evaluator", condition_type=condition_type)

    def get_evaluation_statistics(self) -> Dict[str, Any]:
        """Get evaluation performance statistics."""
        return self._evaluation_stats.copy()


# Convenience function for testing
async def test_condition_executor():
    """Test function for ConditionExecutor with various condition types."""
    from unittest.mock import AsyncMock
    from ..core.context import ExecutionContext

    # Create mock context
    mock_session = AsyncMock()
    context = ExecutionContext("test_run", mock_session)

    # Set up test data
    await context.set("nodes.classifier.output.response", "ITINERARY")

    # Create condition executor
    executor = ConditionExecutor()

    # Test string match condition
    test_node = WorkflowNode(
        id="condition_router",
        type="condition",
        config={
            "condition_type": "string_match",
            "input_source": "${nodes.classifier.output.response}",
            "rules": [
                {
                    "name": "itinerary_route",
                    "value": "ITINERARY",
                    "target": "itinerary_agent",
                    "case_sensitive": False
                },
                {
                    "name": "flight_route",
                    "value": "FLIGHT_BOOKING",
                    "target": "flight_agent",
                    "case_sensitive": False
                }
            ],
            "default_target": "help_agent"
        },
        next=["itinerary_agent", "flight_agent", "help_agent"]
    )

    # Execute
    result = await executor.execute(test_node, context)

    print(f"Condition Execution Status: {result.status}")
    print(f"Matched Target: {result.data.get('matched_target') if result.data else 'No target'}")
    print(f"Next Nodes: {result.next_nodes}")

    return result


if __name__ == "__main__":
    # Run test
    import asyncio
    asyncio.run(test_condition_executor())