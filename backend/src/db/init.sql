-- PostgreSQL initialization script
-- Runs once when container is first created

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Note: Tables are created by SQLAlchemy on startup (Base.metadata.create_all)
-- This file can hold seed data or additional indexes if needed later

-- Add gemini_metadata column if it doesn't exist (for Google AI integration)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='assets' AND column_name='gemini_metadata'
    ) THEN
        ALTER TABLE assets ADD COLUMN gemini_metadata TEXT;
    END IF;
END $$;

SELECT 'Database initialized' AS status;
