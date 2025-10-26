"""
NodeExecutor Framework - Abstract Base Classes and Execution Infrastructure

This module provides the foundation for all workflow node execution, including:
- Abstract NodeExecutor base class with standardized interface
- ExecutionResult models for consistent response handling
- RetryPolicy framework for intelligent failure recovery
- ValidationResult system for configuration validation
- Timeout management and error handling patterns
- Performance monitoring and metrics integration

Author: AI Workflow Engine Team
"""

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union, Callable, Awaitable
import structlog

from .context import ExecutionContext
from ..core.schemas import WorkflowNode

# Set up structured logging
logger = structlog.get_logger(__name__)


class ExecutionStatus(Enum):
    """Standardized execution status values"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    SKIPPED = "skipped"


class RetryDecision(Enum):
    """Retry decision options"""
    RETRY = "retry"
    FAIL = "fail"
    SKIP = "skip"


class ValidationSeverity(Enum):
    """Configuration validation severity levels"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Represents a configuration validation issue"""
    severity: ValidationSeverity
    message: str
    field: Optional[str] = None
    suggestion: Optional[str] = None
    details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "severity": self.severity.value,
            "message": self.message,
            "field": self.field,
            "suggestion": self.suggestion,
            "details": self.details
        }


@dataclass
class ValidationResult:
    """Result of configuration validation"""
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        """Get only error-level issues"""
        return [issue for issue in self.issues if issue.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Get only warning-level issues"""
        return [issue for issue in self.issues if issue.severity == ValidationSeverity.WARNING]

    def add_error(self, message: str, field: Optional[str] = None, suggestion: Optional[str] = None):
        """Add an error issue"""
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message=message,
            field=field,
            suggestion=suggestion
        ))
        self.is_valid = False

    def add_warning(self, message: str, field: Optional[str] = None, suggestion: Optional[str] = None):
        """Add a warning issue"""
        self.issues.append(ValidationIssue(
            severity=ValidationSeverity.WARNING,
            message=message,
            field=field,
            suggestion=suggestion
        ))

    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        """Merge with another validation result"""
        merged = ValidationResult(
            is_valid=self.is_valid and other.is_valid,
            issues=self.issues + other.issues
        )
        return merged


@dataclass
class ExecutionMetrics:
    """Performance metrics for node execution"""
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    cpu_time_ms: Optional[float] = None
    network_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def mark_completed(self):
        """Mark execution as completed and calculate duration"""
        self.end_time = datetime.now(timezone.utc)
        if self.start_time:
            duration = self.end_time - self.start_time
            self.duration_ms = duration.total_seconds() * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "memory_usage_mb": self.memory_usage_mb,
            "cpu_time_ms": self.cpu_time_ms,
            "network_calls": self.network_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses
        }


@dataclass
class ExecutionResult:
    """Standardized result from node execution"""
    # Core result data
    status: ExecutionStatus
    data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    # Execution metadata
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    node_id: Optional[str] = None
    node_type: Optional[str] = None

    # Performance and monitoring
    metrics: Optional[ExecutionMetrics] = None
    logs: List[str] = field(default_factory=list)

    # Retry and recovery
    retry_count: int = 0
    can_retry: bool = True

    # Context integration
    context_updates: Dict[str, Any] = field(default_factory=dict)
    
    # Conditional routing
    next_nodes: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if execution was successful"""
        return self.status == ExecutionStatus.SUCCESS

    @property
    def failed(self) -> bool:
        """Check if execution failed"""
        return self.status in [ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT, ExecutionStatus.CANCELLED]

    @property
    def should_retry(self) -> bool:
        """Check if execution should be retried"""
        return self.failed and self.can_retry

    def add_log(self, message: str, level: str = "info"):
        """Add a log message"""
        timestamp = datetime.now(timezone.utc).isoformat()
        self.logs.append(f"[{timestamp}] [{level.upper()}] {message}")

    def set_error(self, error: Exception, details: Optional[str] = None):
        """Set error information from exception"""
        self.status = ExecutionStatus.FAILED
        self.error = {
            "type": type(error).__name__,
            "message": str(error),
            "details": details
        }
        self.add_log(f"Execution failed: {error}", "error")

    def set_timeout(self, timeout_seconds: int):
        """Mark execution as timed out"""
        self.status = ExecutionStatus.TIMEOUT
        self.error = {
            "type": "TimeoutError",
            "message": f"Execution timed out after {timeout_seconds} seconds",
            "timeout_seconds": timeout_seconds
        }
        self.add_log(f"Execution timed out after {timeout_seconds}s", "error")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "execution_id": self.execution_id,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "logs": self.logs,
            "retry_count": self.retry_count,
            "can_retry": self.can_retry,
            "context_updates": self.context_updates
        }


@dataclass
class RetryPolicy:
    """Configurable retry policy for node execution failures"""
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_backoff: bool = True
    jitter: bool = True
    jitter_range: float = 0.1

    # Retry conditions
    retry_on_timeout: bool = True
    retry_on_network_error: bool = True
    retry_on_rate_limit: bool = True
    retry_on_server_error: bool = True
    retry_on_authentication_error: bool = False
    retry_on_validation_error: bool = False

    # Custom retry condition
    custom_retry_condition: Optional[Callable[[Exception], bool]] = None

    def should_retry(self, attempt: int, error: Exception) -> RetryDecision:
        """
        Determine if execution should be retried based on attempt count and error type.

        Args:
            attempt: Current attempt number (1-based)
            error: Exception that caused the failure

        Returns:
            RetryDecision indicating whether to retry, fail, or skip
        """
        # Check attempt limit
        if attempt >= self.max_attempts:
            return RetryDecision.FAIL

        # Check custom condition first
        if self.custom_retry_condition:
            if self.custom_retry_condition(error):
                return RetryDecision.RETRY
            else:
                return RetryDecision.FAIL

        # Check standard error types
        error_type = type(error).__name__
        error_message = str(error).lower()

        # Timeout errors
        if error_type in ["TimeoutError", "asyncio.TimeoutError"] and self.retry_on_timeout:
            return RetryDecision.RETRY
        elif "timeout" in error_message and self.retry_on_timeout:
            return RetryDecision.RETRY

        # Network errors
        if ("connection" in error_message or "network" in error_message) and self.retry_on_network_error:
            return RetryDecision.RETRY

        # Rate limiting
        if ("rate limit" in error_message or "too many requests" in error_message) and self.retry_on_rate_limit:
            return RetryDecision.RETRY

        # Server errors (5xx)
        if ("server error" in error_message or "500" in error_message) and self.retry_on_server_error:
            return RetryDecision.RETRY

        # Authentication errors (typically don't retry)
        if ("unauthorized" in error_message or "401" in error_message):
            return RetryDecision.FAIL if not self.retry_on_authentication_error else RetryDecision.RETRY

        # Validation errors (typically don't retry)
        if ("validation" in error_message or "400" in error_message):
            return RetryDecision.FAIL if not self.retry_on_validation_error else RetryDecision.RETRY

        # Default: fail for unknown errors unless explicitly configured to retry
        return RetryDecision.FAIL

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry attempt.

        Args:
            attempt: Current attempt number (1-based)

        Returns:
            Delay in seconds before next attempt
        """
        if self.exponential_backoff:
            delay = self.base_delay_seconds * (2 ** (attempt - 1))
        else:
            delay = self.base_delay_seconds

        # Apply maximum delay limit
        delay = min(delay, self.max_delay_seconds)

        # Add jitter to prevent thundering herd
        if self.jitter:
            import random
            jitter_amount = delay * self.jitter_range
            delay += random.uniform(-jitter_amount, jitter_amount)

        return max(0, delay)


class NodeExecutor(ABC):
    """
    Abstract base class for all workflow node executors.

    Provides the standard interface and common functionality for executing
    workflow nodes with proper error handling, retry logic, and monitoring.
    """

    def __init__(self, default_timeout: int = 300):
        """
        Initialize the node executor.

        Args:
            default_timeout: Default timeout in seconds for node execution
        """
        self.default_timeout = default_timeout
        self.logger = structlog.get_logger(self.__class__.__name__)

    @abstractmethod
    async def execute_impl(
        self,
        node: WorkflowNode,
        context: ExecutionContext
    ) -> ExecutionResult:
        """
        Implement the actual node execution logic.

        This method should be implemented by concrete node executors
        to provide the specific execution behavior for their node type.

        Args:
            node: The workflow node to execute
            context: The execution context containing workflow state

        Returns:
            ExecutionResult with the outcome of the execution
        """
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> ValidationResult:
        """
        Validate the node configuration.

        Args:
            config: Node configuration dictionary

        Returns:
            ValidationResult indicating if configuration is valid
        """
        pass

    def get_retry_policy(self) -> RetryPolicy:
        """
        Get the retry policy for this node type.

        Can be overridden by concrete implementations to provide
        custom retry behavior.

        Returns:
            RetryPolicy defining retry behavior
        """
        return RetryPolicy()

    def get_timeout(self, config: Dict[str, Any]) -> int:
        """
        Get execution timeout from configuration.

        Args:
            config: Node configuration dictionary

        Returns:
            Timeout in seconds
        """
        return config.get('timeout', self.default_timeout)

    async def execute(
        self,
        node: WorkflowNode,
        context: ExecutionContext
    ) -> ExecutionResult:
        """
        Execute a workflow node with full error handling and retry logic.

        This is the main entry point that orchestrates the entire execution
        process including validation, timeout handling, retries, and monitoring.

        Args:
            node: The workflow node to execute
            context: The execution context containing workflow state

        Returns:
            ExecutionResult with the outcome of the execution
        """
        execution_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)

        # Initialize execution result
        result = ExecutionResult(
            status=ExecutionStatus.PENDING,
            execution_id=execution_id,
            node_id=node.id,
            node_type=node.type,
            metrics=ExecutionMetrics(start_time=start_time)
        )

        await self.logger.ainfo(
            "Starting node execution",
            node_id=node.id,
            node_type=node.type,
            execution_id=execution_id
        )

        try:
            # 1. Validate configuration
            validation_result = self.validate_config(node.config)
            if not validation_result.is_valid:
                result.status = ExecutionStatus.FAILED
                result.error = {
                    "type": "ValidationError",
                    "message": "Node configuration validation failed",
                    "validation_issues": [issue.to_dict() for issue in validation_result.errors]
                }
                result.can_retry = False
                return result

            # 2. Execute with retry logic
            retry_policy = self.get_retry_policy()
            timeout_seconds = self.get_timeout(node.config)

            attempt = 1
            while attempt <= retry_policy.max_attempts:
                try:
                    result.retry_count = attempt - 1
                    result.status = ExecutionStatus.RUNNING

                    await self.logger.adebug(
                        "Executing node attempt",
                        node_id=node.id,
                        attempt=attempt,
                        max_attempts=retry_policy.max_attempts,
                        execution_id=execution_id
                    )

                    # Execute with timeout
                    execution_result = await asyncio.wait_for(
                        self.execute_impl(node, context),
                        timeout=timeout_seconds
                    )

                    # Merge results
                    execution_result.execution_id = execution_id
                    execution_result.node_id = node.id
                    execution_result.node_type = node.type
                    execution_result.retry_count = attempt - 1

                    if execution_result.metrics:
                        execution_result.metrics.mark_completed()

                    # Apply context updates if provided
                    if execution_result.context_updates:
                        await context.merge(execution_result.context_updates)

                    await self.logger.ainfo(
                        "Node execution completed",
                        node_id=node.id,
                        status=execution_result.status.value,
                        attempt=attempt,
                        execution_id=execution_id,
                        duration_ms=execution_result.metrics.duration_ms if execution_result.metrics else None
                    )

                    return execution_result

                except asyncio.TimeoutError:
                    result.set_timeout(timeout_seconds)

                    await self.logger.awarning(
                        "Node execution timeout",
                        node_id=node.id,
                        timeout_seconds=timeout_seconds,
                        attempt=attempt,
                        execution_id=execution_id
                    )

                    # Check if we should retry timeout
                    if retry_policy.should_retry(attempt, TimeoutError()) == RetryDecision.RETRY:
                        if attempt < retry_policy.max_attempts:
                            delay = retry_policy.get_delay(attempt)
                            await asyncio.sleep(delay)
                            attempt += 1
                            continue

                    result.metrics.mark_completed()
                    return result

                except Exception as e:
                    await self.logger.aerror(
                        "Node execution error",
                        node_id=node.id,
                        error=str(e),
                        error_type=type(e).__name__,
                        attempt=attempt,
                        execution_id=execution_id
                    )

                    # Check retry decision
                    retry_decision = retry_policy.should_retry(attempt, e)

                    if retry_decision == RetryDecision.RETRY and attempt < retry_policy.max_attempts:
                        result.status = ExecutionStatus.RETRYING
                        delay = retry_policy.get_delay(attempt)

                        await self.logger.ainfo(
                            "Retrying node execution",
                            node_id=node.id,
                            attempt=attempt + 1,
                            delay_seconds=delay,
                            execution_id=execution_id
                        )

                        await asyncio.sleep(delay)
                        attempt += 1
                        continue

                    elif retry_decision == RetryDecision.SKIP:
                        result.status = ExecutionStatus.SKIPPED
                        result.add_log(f"Execution skipped due to error: {e}")
                        result.metrics.mark_completed()
                        return result

                    else:
                        # Fail permanently
                        result.set_error(e, f"Failed after {attempt} attempts")
                        result.metrics.mark_completed()
                        return result

            # Should not reach here, but handle just in case
            result.status = ExecutionStatus.FAILED
            result.error = {
                "type": "MaxAttemptsExceeded",
                "message": f"Execution failed after {retry_policy.max_attempts} attempts"
            }
            result.metrics.mark_completed()
            return result

        except Exception as e:
            # Catch-all for unexpected errors
            await self.logger.aerror(
                "Unexpected error in node execution",
                node_id=node.id,
                error=str(e),
                error_type=type(e).__name__,
                execution_id=execution_id
            )

            result.set_error(e, "Unexpected error during execution")
            result.can_retry = False
            result.metrics.mark_completed()
            return result

    async def pre_execute(
        self,
        node: WorkflowNode,
        context: ExecutionContext
    ) -> Optional[Dict[str, Any]]:
        """
        Hook called before node execution.

        Can be overridden by concrete implementations to perform
        setup tasks or context preparation.

        Args:
            node: The workflow node to execute
            context: The execution context

        Returns:
            Optional data to pass to the execution
        """
        return None

    async def post_execute(
        self,
        node: WorkflowNode,
        context: ExecutionContext,
        result: ExecutionResult
    ) -> None:
        """
        Hook called after node execution.

        Can be overridden by concrete implementations to perform
        cleanup tasks or result processing.

        Args:
            node: The workflow node that was executed
            context: The execution context
            result: The execution result
        """
        pass

    def get_node_info(self) -> Dict[str, Any]:
        """
        Get information about this node executor type.

        Returns:
            Dictionary with executor metadata
        """
        return {
            "executor_class": self.__class__.__name__,
            "node_type": getattr(self, 'NODE_TYPE', 'unknown'),
            "default_timeout": self.default_timeout,
            "supports_retry": True,
            "supports_timeout": True
        }


class ExecutorRegistry:
    """
    Registry for managing node executors by type.

    Provides centralized registration and lookup of node executors
    for different node types in the workflow engine.
    """

    def __init__(self):
        self._executors: Dict[str, NodeExecutor] = {}
        self.logger = structlog.get_logger("ExecutorRegistry")

    def register(self, node_type: str, executor: NodeExecutor) -> None:
        """
        Register a node executor for a specific node type.

        Args:
            node_type: The type of nodes this executor handles
            executor: The executor instance
        """
        self._executors[node_type] = executor
        self.logger.info(
            "Registered node executor",
            node_type=node_type,
            executor_class=executor.__class__.__name__
        )

    def get_executor(self, node_type: str) -> Optional[NodeExecutor]:
        """
        Get the registered executor for a node type.

        Args:
            node_type: The type of node to get executor for

        Returns:
            NodeExecutor instance or None if not found
        """
        return self._executors.get(node_type)

    def list_executors(self) -> Dict[str, str]:
        """
        List all registered executors.

        Returns:
            Dictionary mapping node types to executor class names
        """
        return {
            node_type: executor.__class__.__name__
            for node_type, executor in self._executors.items()
        }

    def is_supported(self, node_type: str) -> bool:
        """
        Check if a node type is supported.

        Args:
            node_type: The node type to check

        Returns:
            True if supported, False otherwise
        """
        return node_type in self._executors

    async def execute_node(
        self,
        node: WorkflowNode,
        context: ExecutionContext
    ) -> ExecutionResult:
        """
        Execute a node using the appropriate registered executor.

        Args:
            node: The workflow node to execute
            context: The execution context

        Returns:
            ExecutionResult from the appropriate executor
        """
        executor = self.get_executor(node.type)

        if not executor:
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                node_id=node.id,
                node_type=node.type
            )
            result.set_error(
                ValueError(f"No executor registered for node type: {node.type}"),
                f"Available node types: {list(self._executors.keys())}"
            )
            return result

        return await executor.execute(node, context)


# Global executor registry instance
executor_registry = ExecutorRegistry()


# Utility functions for common validation patterns
def validate_required_config(
    config: Dict[str, Any],
    required_fields: List[str]
) -> ValidationResult:
    """
    Validate that required configuration fields are present.

    Args:
        config: Configuration dictionary to validate
        required_fields: List of required field names

    Returns:
        ValidationResult with any missing field errors
    """
    result = ValidationResult(is_valid=True)

    for field in required_fields:
        if field not in config:
            result.add_error(
                f"Required field '{field}' is missing",
                field=field,
                suggestion=f"Add '{field}' to the node configuration"
            )
        elif config[field] is None:
            result.add_error(
                f"Required field '{field}' cannot be null",
                field=field,
                suggestion=f"Provide a valid value for '{field}'"
            )
        elif isinstance(config[field], str) and not config[field].strip():
            result.add_error(
                f"Required field '{field}' cannot be empty",
                field=field,
                suggestion=f"Provide a non-empty value for '{field}'"
            )

    return result


def validate_timeout_config(config: Dict[str, Any]) -> ValidationResult:
    """
    Validate timeout configuration.

    Args:
        config: Configuration dictionary to validate

    Returns:
        ValidationResult with any timeout validation issues
    """
    result = ValidationResult(is_valid=True)

    if 'timeout' in config:
        timeout = config['timeout']

        if not isinstance(timeout, (int, float)):
            result.add_error(
                "Timeout must be a number",
                field='timeout',
                suggestion="Use an integer or float value for timeout in seconds"
            )
        elif timeout <= 0:
            result.add_error(
                "Timeout must be positive",
                field='timeout',
                suggestion="Use a positive number for timeout in seconds"
            )
        elif timeout > 3600:  # 1 hour
            result.add_warning(
                "Timeout is very long (>1 hour)",
                field='timeout',
                suggestion="Consider using a shorter timeout to avoid hanging executions"
            )

    return result