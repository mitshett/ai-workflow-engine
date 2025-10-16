"""AI Workflow Engine - Database Models

SQLAlchemy models that define the database schema.
Tables are automatically created from these models on startup.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Workflow(Base):
    """Workflow definition storage."""

    __tablename__ = "workflows"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    definition = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    runs = relationship("WorkflowRun", back_populates="workflow", cascade="all, delete-orphan")

    # Constraints
    __table_args__ = (
        CheckConstraint("LENGTH(TRIM(name)) > 0", name="workflows_name_not_empty"),
        CheckConstraint("definition IS NOT NULL", name="workflows_definition_not_null"),
        Index("idx_workflows_name", "name"),
        Index("idx_workflows_created", "created_at"),
    )


class WorkflowRun(Base):
    """Individual workflow execution instances."""

    __tablename__ = "workflow_runs"

    id = Column(String, primary_key=True)
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="pending")
    context = Column(JSONB, default={})
    current_node = Column(String)
    version = Column(BigInteger, default=1)
    last_snapshot_sequence = Column(BigInteger, default=0)
    input_data = Column(JSONB, default={})
    output_data = Column(JSONB, default={})
    error_info = Column(JSONB)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="runs")
    node_executions = relationship("NodeExecution", back_populates="run", cascade="all, delete-orphan")
    events = relationship("WorkflowEvent", back_populates="run", cascade="all, delete-orphan")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'paused', 'completed', 'failed', 'cancelled')",
            name="workflow_runs_status_valid"
        ),
        CheckConstraint("version > 0", name="workflow_runs_version_positive"),
        CheckConstraint("last_snapshot_sequence >= 0", name="workflow_runs_snapshot_sequence_valid"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="workflow_runs_finished_after_started"
        ),
        Index("idx_runs_status", "status", postgresql_where="status IN ('running', 'paused')"),
        Index("idx_runs_workflow", "workflow_id"),
        Index("idx_runs_status_updated", "status", "updated_at",
              postgresql_where="status IN ('running', 'paused', 'failed')"),
        Index("idx_runs_context_gin", "context", postgresql_using="gin"),
        Index("idx_runs_input_gin", "input_data", postgresql_using="gin"),
    )


class NodeExecution(Base):
    """Individual node execution tracking."""

    __tablename__ = "node_executions"

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String, nullable=False)
    node_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    input = Column(JSONB, default={})
    output = Column(JSONB, default={})
    error = Column(JSONB)
    retry_count = Column(Integer, default=0)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)

    # Relationships
    run = relationship("WorkflowRun", back_populates="node_executions")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'skipped', 'retry')",
            name="node_executions_status_valid"
        ),
        CheckConstraint(
            "node_type IN ('agent', 'tool', 'mcp_server', 'condition')",
            name="node_executions_node_type_valid"
        ),
        CheckConstraint("retry_count >= 0", name="node_executions_retry_count_valid"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="node_executions_duration_positive"
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="node_executions_finished_after_started"
        ),
        Index("idx_executions_run", "run_id"),
        Index("idx_executions_status", "status"),
        Index("idx_executions_node_type", "node_type"),
        Index("idx_executions_input_gin", "input", postgresql_using="gin"),
        Index("idx_executions_output_gin", "output", postgresql_using="gin"),
    )


class WorkflowEvent(Base):
    """Event sourcing for workflow state management."""

    __tablename__ = "workflow_events"

    event_id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    sequence_number = Column(BigInteger, nullable=False)
    event_type = Column(String, nullable=False)
    node_id = Column(String)
    timestamp = Column(DateTime, default=func.now())
    payload = Column(JSONB, default={})
    correlation_id = Column(String)

    # Relationships
    run = relationship("WorkflowRun", back_populates="events")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint("sequence_number > 0", name="workflow_events_sequence_positive"),
        CheckConstraint(
            "LENGTH(TRIM(event_type)) > 0",
            name="workflow_events_event_type_not_empty"
        ),
        UniqueConstraint("run_id", "sequence_number", name="uq_events_run_sequence"),
        Index("idx_events_run_sequence", "run_id", "sequence_number"),
        Index("idx_events_type", "event_type"),
        Index("idx_events_payload_gin", "payload", postgresql_using="gin"),
    )


class SystemConfig(Base):
    """System configuration storage."""

    __tablename__ = "system_config"

    key = Column(String, primary_key=True)
    value = Column(JSONB, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# Version increment trigger logic
@event.listens_for(WorkflowRun, "before_update")
def increment_version(mapper, connection, target):
    """Automatically increment version when context or status changes."""
    if mapper.has_identity(target):
        # Get the original state
        original = connection.execute(
            mapper.selectable.select().where(
                mapper.selectable.c.id == target.id
            )
        ).first()

        if original:
            # Check if context or status changed
            if (target.context != original.context or
                target.status != original.status):
                target.version = original.version + 1


def create_default_config() -> list[dict[str, Any]]:
    """Return default system configuration data."""
    return [
        {
            "key": "snapshot_interval",
            "value": 100,
            "description": "Number of events after which to create a snapshot"
        },
        {
            "key": "max_retry_attempts",
            "value": 3,
            "description": "Default maximum retry attempts for failed nodes"
        },
        {
            "key": "default_timeout_seconds",
            "value": 300,
            "description": "Default timeout for node execution in seconds"
        },
        {
            "key": "event_retention_days",
            "value": 90,
            "description": "Number of days to retain events after workflow completion"
        },
        {
            "key": "enable_parallel_execution",
            "value": True,
            "description": "Enable parallel execution of independent nodes"
        }
    ]