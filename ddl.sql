CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE artifact_chunks (
    id SERIAL PRIMARY KEY,
    repo TEXT,
    team TEXT,
    path TEXT,
    block_name TEXT,
    block_type TEXT,
    block_start_line INTEGER,
    block_end_line INTEGER,
    content TEXT,
    tables_ref TEXT[],
    columns_ref TEXT[],
    dependencies JSONB DEFAULT '{}',
    summary TEXT,
    embedding vector(384)
);