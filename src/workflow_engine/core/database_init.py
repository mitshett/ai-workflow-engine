"""AI Workflow Engine - Database Initialization

Simple database setup that automatically creates tables from models on startup.
"""

import asyncio
import os
from typing import Optional

import structlog

from ..persistence.database import create_database_if_not_exists, init_database

logger = structlog.get_logger(__name__)


async def setup_database(database_url: Optional[str] = None, create_db: bool = True) -> None:
    """Set up database with automatic table creation.

    Args:
        database_url: PostgreSQL connection URL. If None, uses environment variable.
        create_db: Whether to create the database if it doesn't exist.
    """
    # Get database URL
    if not database_url:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:password@localhost:5432/ai_workflow_engine"
        )

    logger.info("Setting up AI Workflow Engine database", url=database_url)

    try:
        # Create database if it doesn't exist (optional)
        if create_db:
            await create_database_if_not_exists(database_url)

        # Initialize database (creates tables from models)
        await init_database(database_url)

        logger.info("✅ Database setup completed successfully!")
        logger.info("📋 Tables created: workflows, workflow_runs, node_executions, workflow_events, system_config")
        logger.info("🚀 Ready to execute workflows!")

    except Exception as e:
        logger.error("❌ Database setup failed", error=str(e))
        raise


def main() -> None:
    """Main function for running database setup as a script."""
    import sys

    # Configure basic logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Parse command line arguments
    database_url = None
    if len(sys.argv) > 1:
        database_url = sys.argv[1]

    # Run database setup
    try:
        asyncio.run(setup_database(database_url))
        print("\n🎉 Database is ready for AI workflow execution!")
        print("\n💡 Next steps:")
        print("   1. Set DATABASE_URL environment variable")
        print("   2. Start your workflow engine application")
        print("   3. Begin creating and executing workflows!")
    except Exception as e:
        print(f"\n💥 Database setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()