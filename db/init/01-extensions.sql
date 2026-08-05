-- Runs automatically the first time the database container starts with an
-- empty data volume. The backend also runs these statements on startup, so a
-- pre-existing volume still gets the extensions.

-- pgvector: adds the `vector` column type plus similarity operators (<=>, <->).
CREATE EXTENSION IF NOT EXISTS vector;

-- Used for gen_random_uuid() if you ever want the database to mint ids.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
