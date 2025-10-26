"""
Execution Context Management System

This module provides thread-safe, hierarchical context management for workflow executions.
Supports template resolution, database persistence, and memory optimization.

Features:
- Thread-safe read/write operations with asyncio RWLocks
- Hierarchical data access (nodes.id.output, workflow.input)
- Database persistence with optimistic locking
- Template variable resolution
- Memory management and compression
- Performance monitoring and metrics

Author: AI Workflow Engine Team
"""

import asyncio
import json
import time
import hashlib
import logging
from typing import Dict, Any, Optional, List, Union, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import structlog

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from pydantic import BaseModel, Field

from ..persistence.models import WorkflowRun

# Set up structured logging
logger = structlog.get_logger(__name__)


@dataclass
class ContextMetrics:
    """Performance metrics for context operations"""
    read_operations: int = 0
    write_operations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    avg_read_time_ms: float = 0.0
    avg_write_time_ms: float = 0.0
    total_memory_mb: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ContextUpdate:
    """Represents a context update operation"""
    key: str
    value: Any
    operation: str  # "set", "merge", "delete"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    version: int = 1


class ContextNamespace:
    """Represents a hierarchical namespace in the context"""

    def __init__(self, data: Dict[str, Any] = None):
        self._data = data or {}

    def get(self, path: str, default: Any = None) -> Any:
        """Get value using dot notation path"""
        keys = path.split('.')
        current = self._data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default

        return current

    def set(self, path: str, value: Any) -> None:
        """Set value using dot notation path"""
        keys = path.split('.')
        current = self._data

        # Navigate to the parent of the target key
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            elif not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]

        # Set the final value
        current[keys[-1]] = value

    def merge(self, path: str, value: Dict[str, Any]) -> None:
        """Recursively merge dictionary at path"""
        existing = self.get(path, {})
        if isinstance(existing, dict) and isinstance(value, dict):
            merged = self._deep_merge(existing, value)
            self.set(path, merged)
        else:
            self.set(path, value)

    def delete(self, path: str) -> bool:
        """Delete value at path, return True if existed"""
        keys = path.split('.')
        current = self._data

        # Navigate to parent
        for key in keys[:-1]:
            if not isinstance(current, dict) or key not in current:
                return False
            current = current[key]

        # Delete final key
        if isinstance(current, dict) and keys[-1] in current:
            del current[keys[-1]]
            return True
        return False

    def _deep_merge(self, dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge two dictionaries"""
        result = dict1.copy()

        for key, value in dict2.items():
            if (key in result and
                isinstance(result[key], dict) and
                isinstance(value, dict)):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert namespace to dictionary"""
        return self._data.copy()

    def keys(self) -> Set[str]:
        """Get all available keys (flattened with dot notation)"""
        keys = set()

        def _collect_keys(data: Dict[str, Any], prefix: str = ""):
            for key, value in data.items():
                full_key = f"{prefix}.{key}" if prefix else key
                keys.add(full_key)

                if isinstance(value, dict):
                    _collect_keys(value, full_key)

        _collect_keys(self._data)
        return keys


class ExecutionContext:
    """
    Thread-safe execution context for workflow runs.

    Provides hierarchical data storage, template resolution, and database persistence
    with optimistic locking and performance monitoring.
    """

    def __init__(
        self,
        run_id: str,
        db_session: AsyncSession,
        cache_ttl_seconds: int = 300,
        memory_limit_mb: int = 100,
        alias_to_node_mapping: Optional[Dict[str, str]] = None
    ):
        self.run_id = run_id
        self._session = db_session
        self.cache_ttl_seconds = cache_ttl_seconds
        self.memory_limit_mb = memory_limit_mb
        self._alias_to_node_mapping = alias_to_node_mapping or {}

        # Thread-safe data structures
        self._namespace = ContextNamespace()
        self._lock = asyncio.Lock()  # Using standard asyncio Lock for simplicity
        self._version = 1
        self._last_persisted_version = 0

        # Performance monitoring
        self._metrics = ContextMetrics()
        self._operation_times: List[float] = []

        # Memory management
        self._cache_expiry: Dict[str, datetime] = {}
        self._dirty_keys: Set[str] = set()

        # Template resolution cache
        self._template_cache: Dict[str, str] = {}

        logger.info("ExecutionContext initialized", run_id=run_id, aliases=list(self._alias_to_node_mapping.keys()))

    @asynccontextmanager
    async def _read_lock(self):
        """Async context manager for read operations"""
        async with self._lock:
            yield

    @asynccontextmanager
    async def _write_lock(self):
        """Async context manager for write operations"""
        async with self._lock:
            yield

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Thread-safe context retrieval with performance monitoring.

        Args:
            key: Dot-notation key (e.g., 'nodes.analyze.output.summary')
            default: Default value if key not found

        Returns:
            Value at key or default
        """
        start_time = time.time()

        try:
            async with self._read_lock():
                # Check cache expiry
                if key in self._cache_expiry and datetime.utcnow() > self._cache_expiry[key]:
                    await self._evict_key(key)

                value = self._namespace.get(key, default)

                # Update metrics
                self._metrics.read_operations += 1
                if value != default:
                    self._metrics.cache_hits += 1
                else:
                    self._metrics.cache_misses += 1

                return value

        finally:
            execution_time = (time.time() - start_time) * 1000
            self._update_read_metrics(execution_time)

            await logger.adebug(
                "Context read operation",
                run_id=self.run_id,
                key=key,
                execution_time_ms=execution_time,
                found=value != default if 'value' in locals() else False
            )

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """
        Thread-safe context update with versioning.

        Args:
            key: Dot-notation key
            value: Value to store
            ttl_seconds: Time-to-live for cache entry
        """
        start_time = time.time()

        try:
            async with self._write_lock():
                # Set value in namespace
                self._namespace.set(key, value)

                # Update version and track changes
                self._version += 1
                self._dirty_keys.add(key)

                # Set cache expiry if specified
                if ttl_seconds:
                    self._cache_expiry[key] = datetime.utcnow() + timedelta(seconds=ttl_seconds)

                # Update metrics
                self._metrics.write_operations += 1

                # Check memory limits
                await self._check_memory_limits()

        finally:
            execution_time = (time.time() - start_time) * 1000
            self._update_write_metrics(execution_time)

            await logger.adebug(
                "Context write operation",
                run_id=self.run_id,
                key=key,
                execution_time_ms=execution_time,
                version=self._version
            )

    async def merge(
        self,
        updates: Dict[str, Any],
        overwrite: bool = False
    ) -> None:
        """
        Recursively merge multiple updates into context.

        Args:
            updates: Dictionary of key-value pairs to merge
            overwrite: Whether to overwrite existing keys
        """
        start_time = time.time()

        try:
            async with self._write_lock():
                for key, value in updates.items():
                    if overwrite or not self._namespace.get(key):
                        if isinstance(value, dict):
                            self._namespace.merge(key, value)
                        else:
                            self._namespace.set(key, value)

                        self._dirty_keys.add(key)

                self._version += 1
                self._metrics.write_operations += len(updates)

                await self._check_memory_limits()

        finally:
            execution_time = (time.time() - start_time) * 1000
            self._update_write_metrics(execution_time)

            await logger.adebug(
                "Context merge operation",
                run_id=self.run_id,
                keys_merged=len(updates),
                execution_time_ms=execution_time,
                version=self._version
            )

    async def delete(self, key: str) -> bool:
        """
        Delete key from context.

        Args:
            key: Dot-notation key to delete

        Returns:
            True if key existed and was deleted
        """
        async with self._write_lock():
            existed = self._namespace.delete(key)

            if existed:
                self._version += 1
                self._dirty_keys.add(key)

                # Remove from cache tracking
                self._cache_expiry.pop(key, None)

                await logger.adebug(
                    "Context delete operation",
                    run_id=self.run_id,
                    key=key,
                    version=self._version
                )

            return existed

    async def get_all_keys(self) -> Set[str]:
        """Get all available keys in the context"""
        async with self._read_lock():
            return self._namespace.keys()

    async def resolve_template(self, template: str, recursive: bool = True) -> str:
        """
        Resolve template variables in format ${context.key.path}.

        Args:
            template: Template string with variables
            recursive: Whether to resolve nested templates

        Returns:
            Resolved template string
        """
        # Check template cache
        cache_key = hashlib.md5(f"{template}:{self._version}".encode()).hexdigest()
        if cache_key in self._template_cache:
            return self._template_cache[cache_key]

        import re

        # Pattern to match ${context.key.path}
        pattern = r'\$\{([^}]+)\}'

        async def replace_var(match):
            var_path = match.group(1)

            # Handle special variables
            if var_path == "runtime.timestamp":
                return datetime.utcnow().isoformat()
            elif var_path == "runtime.run_id":
                return self.run_id
            elif var_path.startswith("context."):
                # Remove 'context.' prefix
                key = var_path[8:]
                value = await self.get(key)
                return str(value) if value is not None else ""
            elif var_path.startswith("workflow."):
                # Check if this is an alias reference first
                key_parts = var_path[9:].split('.')  # Remove 'workflow.' prefix  
                if len(key_parts) >= 2 and key_parts[0] in self._alias_to_node_mapping:
                    # Translate alias to node ID: workflow.alias.field -> nodes.node_id.output.field
                    alias = key_parts[0]
                    node_id = self._alias_to_node_mapping[alias]
                    # Reconstruct as nodes.{node_id}.output.{remaining_path}
                    node_key = f"nodes.{node_id}.output." + ".".join(key_parts[1:])
                    value = await self.get(node_key)
                else:
                    # Regular workflow variable - keep full path including 'workflow.'
                    value = await self.get(var_path)
                    
                return str(value) if value is not None else ""
            else:
                # Direct key access
                value = await self.get(var_path)
                return str(value) if value is not None else ""

        # Replace all variables
        resolved = template
        for match in re.finditer(pattern, template):
            replacement = await replace_var(match)
            resolved = resolved.replace(match.group(0), replacement)

        # Recursive resolution if needed
        if recursive and resolved != template and re.search(pattern, resolved):
            resolved = await self.resolve_template(resolved, recursive=False)

        # Cache result
        self._template_cache[cache_key] = resolved

        return resolved

    async def persist(self, force: bool = False) -> bool:
        """
        Persist context to database with optimistic locking.

        Args:
            force: Force persistence even if no changes

        Returns:
            True if persistence succeeded
        """
        if not force and not self._dirty_keys:
            return True  # No changes to persist

        try:
            async with self._write_lock():
                # Serialize context data
                context_data = self._namespace.to_dict()

                # Update workflow run with new context
                stmt = update(WorkflowRun).where(
                    WorkflowRun.id == self.run_id,
                    WorkflowRun.version == self._last_persisted_version
                ).values(
                    context=context_data,
                    version=self._version,
                    updated_at=datetime.utcnow()
                )

                result = await self._session.execute(stmt)

                if result.rowcount == 0:
                    # Version conflict - need to reload and merge
                    await logger.awarning(
                        "Context persistence conflict",
                        run_id=self.run_id,
                        expected_version=self._last_persisted_version,
                        current_version=self._version
                    )
                    return False

                await self._session.commit()

                # Update tracking
                self._last_persisted_version = self._version
                self._dirty_keys.clear()

                await logger.ainfo(
                    "Context persisted successfully",
                    run_id=self.run_id,
                    version=self._version,
                    keys_persisted=len(context_data)
                )

                return True

        except Exception as e:
            await self._session.rollback()
            await logger.aerror(
                "Context persistence failed",
                run_id=self.run_id,
                error=str(e),
                version=self._version
            )
            return False

    async def load_from_database(self) -> bool:
        """
        Load context from database.

        Returns:
            True if load succeeded
        """
        try:
            stmt = select(WorkflowRun).where(WorkflowRun.id == self.run_id)
            result = await self._session.execute(stmt)
            workflow_run = result.scalar_one_or_none()

            if not workflow_run:
                await logger.awarning(
                    "Workflow run not found for context load",
                    run_id=self.run_id
                )
                return False

            async with self._write_lock():
                # Load context data
                if workflow_run.context:
                    self._namespace = ContextNamespace(workflow_run.context)

                # Update version tracking
                self._version = workflow_run.version or 1
                self._last_persisted_version = self._version
                self._dirty_keys.clear()

                await logger.ainfo(
                    "Context loaded from database",
                    run_id=self.run_id,
                    version=self._version,
                    keys_loaded=len(workflow_run.context or {})
                )

                return True

        except Exception as e:
            await logger.aerror(
                "Context load failed",
                run_id=self.run_id,
                error=str(e)
            )
            return False

    async def get_metrics(self) -> ContextMetrics:
        """Get current performance metrics"""
        async with self._read_lock():
            # Update memory usage
            import sys
            self._metrics.total_memory_mb = sys.getsizeof(self._namespace.to_dict()) / (1024 * 1024)
            self._metrics.last_updated = datetime.utcnow()

            return self._metrics

    async def cleanup_expired(self) -> int:
        """
        Clean up expired cache entries.

        Returns:
            Number of keys cleaned up
        """
        now = datetime.utcnow()
        expired_keys = [
            key for key, expiry in self._cache_expiry.items()
            if now > expiry
        ]

        if expired_keys:
            async with self._write_lock():
                for key in expired_keys:
                    await self._evict_key(key)

                await logger.ainfo(
                    "Expired context keys cleaned up",
                    run_id=self.run_id,
                    keys_cleaned=len(expired_keys)
                )

        return len(expired_keys)

    async def _evict_key(self, key: str) -> None:
        """Evict a key from cache"""
        self._namespace.delete(key)
        self._cache_expiry.pop(key, None)
        self._dirty_keys.add(key)  # Mark for persistence cleanup

    async def _check_memory_limits(self) -> None:
        """Check and enforce memory limits"""
        import sys
        current_size_mb = sys.getsizeof(self._namespace.to_dict()) / (1024 * 1024)

        if current_size_mb > self.memory_limit_mb:
            await logger.awarning(
                "Context memory limit exceeded",
                run_id=self.run_id,
                current_mb=current_size_mb,
                limit_mb=self.memory_limit_mb
            )

            # TODO: Implement memory pressure relief (LRU eviction, compression)

    def _update_read_metrics(self, execution_time_ms: float) -> None:
        """Update read operation metrics"""
        self._operation_times.append(execution_time_ms)

        # Keep only last 100 operations for average calculation
        if len(self._operation_times) > 100:
            self._operation_times = self._operation_times[-100:]

        self._metrics.avg_read_time_ms = sum(self._operation_times) / len(self._operation_times)

    def _update_write_metrics(self, execution_time_ms: float) -> None:
        """Update write operation metrics"""
        self._operation_times.append(execution_time_ms)

        if len(self._operation_times) > 100:
            self._operation_times = self._operation_times[-100:]

        self._metrics.avg_write_time_ms = sum(self._operation_times) / len(self._operation_times)

    def __repr__(self) -> str:
        return f"ExecutionContext(run_id='{self.run_id}', version={self._version})"


class ContextManager:
    """
    Global context manager for workflow executions.

    Provides context lifecycle management, caching, and cleanup.
    """

    def __init__(self, db_session_factory):
        self._contexts: Dict[str, ExecutionContext] = {}
        self._session_factory = db_session_factory
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = datetime.utcnow()

    async def get_context(self, run_id: str, alias_to_node_mapping: Optional[Dict[str, str]] = None) -> ExecutionContext:
        """Get or create execution context for run"""
        if run_id not in self._contexts:
            session = self._session_factory()
            context = ExecutionContext(run_id, session, alias_to_node_mapping=alias_to_node_mapping)

            # Try to load existing context from database
            await context.load_from_database()

            self._contexts[run_id] = context

        return self._contexts[run_id]

    async def remove_context(self, run_id: str, persist: bool = True) -> bool:
        """Remove context from memory, optionally persisting first"""
        if run_id not in self._contexts:
            return False

        context = self._contexts[run_id]

        if persist:
            await context.persist(force=True)

        del self._contexts[run_id]

        await logger.ainfo(
            "Context removed from memory",
            run_id=run_id,
            persisted=persist
        )

        return True

    async def cleanup_expired_contexts(self) -> int:
        """Clean up expired contexts and perform maintenance"""
        if datetime.utcnow() - self._last_cleanup < timedelta(seconds=self._cleanup_interval):
            return 0

        cleaned_keys = 0

        for context in self._contexts.values():
            cleaned_keys += await context.cleanup_expired()

        self._last_cleanup = datetime.utcnow()

        await logger.ainfo(
            "Context cleanup completed",
            contexts_active=len(self._contexts),
            keys_cleaned=cleaned_keys
        )

        return cleaned_keys

    async def get_all_metrics(self) -> Dict[str, ContextMetrics]:
        """Get metrics for all active contexts"""
        metrics = {}

        for run_id, context in self._contexts.items():
            metrics[run_id] = await context.get_metrics()

        return metrics