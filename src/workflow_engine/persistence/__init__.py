"""AI Workflow Engine - Persistence Layer

This module handles durable state management:
- Database models and schema (SQLAlchemy)
- Event sourcing implementation
- Snapshot management
- Workflow state persistence and recovery
"""

from .database import (
    DatabaseManager,
    db_manager,
    init_database,
    get_db_session,
    close_database,
    create_database_if_not_exists,
)
from .models import (
    Base,
    Workflow,
    WorkflowRun,
    NodeExecution,
    WorkflowEvent,
    SystemConfig,
    create_default_config,
)

__all__ = [
    # Database management
    "DatabaseManager",
    "db_manager",
    "init_database",
    "get_db_session",
    "close_database",
    "create_database_if_not_exists",
    # Models
    "Base",
    "Workflow",
    "WorkflowRun",
    "NodeExecution",
    "WorkflowEvent",
    "SystemConfig",
    "create_default_config",
]