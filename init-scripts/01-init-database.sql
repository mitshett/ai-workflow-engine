-- AI Workflow Engine - Database Initialization
-- This script runs automatically when the PostgreSQL container starts for the first time

-- Create database extensions that we might need
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create a read-only user for monitoring/analytics (optional)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'workflow_readonly') THEN
        CREATE ROLE workflow_readonly LOGIN PASSWORD 'readonly_password';
    END IF;
END
$$;

-- Grant read-only access to the readonly user
GRANT CONNECT ON DATABASE ai_workflow_engine TO workflow_readonly;
GRANT USAGE ON SCHEMA public TO workflow_readonly;

-- Note: Table-level permissions will be granted after tables are created by SQLAlchemy

-- Log successful initialization
\echo 'AI Workflow Engine PostgreSQL database initialized successfully!'
\echo 'Extensions: uuid-ossp, pgcrypto'
\echo 'Ready for table creation via SQLAlchemy models'