CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE artifact_files (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'code',
    status TEXT NOT NULL DEFAULT 'active',
    last_indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (repo, team, path)
);

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
    embedding vector(384),
    content_hash TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE artifact_relations (
    id SERIAL PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifact_chunks(id) ON DELETE CASCADE,
    related_id INTEGER NOT NULL REFERENCES artifact_chunks(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium',
    reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (artifact_id, related_id, relation_type)
);

CREATE INDEX artifact_chunks_lookup_idx
    ON artifact_chunks (repo, team, path);

CREATE INDEX artifact_relations_artifact_idx
    ON artifact_relations (artifact_id);

CREATE INDEX artifact_relations_related_idx
    ON artifact_relations (related_id);
