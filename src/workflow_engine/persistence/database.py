"""AI Workflow Engine - Database Connection Management

Async database setup with automatic table creation from models.
"""

import os
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
import structlog

from .models import Base, SystemConfig, create_default_config

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Manages database connections and initialization."""

    def __init__(self, database_url: Optional[str] = None):
        """Initialize database manager with connection URL."""
        self.database_url = database_url or self._get_database_url()
        self.engine = None
        self.session_factory = None

    def _get_database_url(self) -> str:
        """Get database URL from environment with defaults."""
        return os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:password@localhost:5432/ai_workflow_engine"
        )

    async def initialize(self) -> None:
        """Initialize database engine and create tables."""
        logger.info("Initializing database connection", url=self.database_url)

        # Create async engine
        self.engine = create_async_engine(
            self.database_url,
            echo=False,  # Set to True for SQL query logging
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,  # Validate connections before use
        )

        # Create session factory
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

        # Create all tables
        await self.create_tables()

        # Initialize default configuration
        await self.initialize_config()

        logger.info("Database initialized successfully")

    async def create_tables(self) -> None:
        """Create all tables from models."""
        logger.info("Creating database tables...")

        async with self.engine.begin() as conn:
            # Create all tables defined in models
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Database tables created successfully")

    async def initialize_config(self) -> None:
        """Initialize system configuration with defaults."""
        logger.info("Initializing system configuration...")

        async with self.get_session() as session:
            # Check if config already exists
            existing_config = await session.execute(
                text("SELECT COUNT(*) FROM system_config")
            )
            count = existing_config.scalar()

            if count == 0:
                # Insert default configuration
                default_configs = create_default_config()
                for config in default_configs:
                    config_obj = SystemConfig(**config)
                    session.add(config_obj)

                await session.commit()
                logger.info("Default system configuration initialized",
                           config_count=len(default_configs))
            else:
                logger.info("System configuration already exists", config_count=count)

    async def get_session(self) -> AsyncSession:
        """Get a database session."""
        if not self.session_factory:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self.session_factory()

    async def close(self) -> None:
        """Close database connections."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self.get_session() as session:
                await session.execute(text("SELECT 1"))
                return True
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return False

    async def get_session_generator(self) -> AsyncGenerator[AsyncSession, None]:
        """Get session generator for dependency injection."""
        async with self.get_session() as session:
            try:
                yield session
            finally:
                await session.close()


# Global database manager instance
db_manager = DatabaseManager()


async def init_database(database_url: Optional[str] = None) -> None:
    """Initialize the global database manager."""
    global db_manager
    if database_url:
        db_manager = DatabaseManager(database_url)
    await db_manager.initialize()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database sessions."""
    async for session in db_manager.get_session_generator():
        yield session


async def close_database() -> None:
    """Close the global database manager."""
    await db_manager.close()


async def create_database_if_not_exists(database_url: str) -> None:
    """Create database if it doesn't exist (for fresh installations)."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    import asyncpg

    # Parse database URL to get components
    if "postgresql+asyncpg://" in database_url:
        # Convert asyncpg URL to regular postgres URL for database creation
        sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_url = database_url

    # Extract database name and create connection URL without database name
    parts = sync_url.rsplit("/", 1)
    if len(parts) == 2:
        base_url, db_name = parts

        try:
            # Try to connect to the target database
            test_engine = create_engine(sync_url)
            test_engine.connect().close()
            test_engine.dispose()
            logger.info("Database already exists", database=db_name)
        except OperationalError:
            # Database doesn't exist, create it
            logger.info("Creating database", database=db_name)

            # Connect to postgres database to create the target database
            postgres_url = f"{base_url}/postgres"
            admin_engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")

            with admin_engine.connect() as conn:
                # Create database
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                logger.info("Database created successfully", database=db_name)

            admin_engine.dispose()
    else:
        logger.warning("Could not parse database name from URL", url=database_url)