-- ============================================================
-- 360Ghar Schema — 09: Vector search and storage bucket
-- ============================================================

-- ============================================================
-- Property embeddings (pgvector for semantic search)
-- ============================================================
CREATE TABLE property_embeddings (
    property_id BIGINT PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    emb_text_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast cosine similarity search
CREATE INDEX idx_property_embeddings_hnsw
    ON property_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TRIGGER update_property_embeddings_updated_at
    BEFORE UPDATE ON property_embeddings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Vector sync watermark tracking
CREATE TABLE vector_sync_state (
    key TEXT PRIMARY KEY,
    last_watermark TIMESTAMPTZ
);

INSERT INTO vector_sync_state (key, last_watermark)
VALUES ('properties', NULL)
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- Storage bucket configuration
-- ============================================================
-- NOTE: RLS policies for storage.objects CANNOT be created via SQL
-- migrations (requires owner permissions). Configure RLS policies
-- manually via Supabase Dashboard:
--   Storage -> Policies -> 360ghar-storage
-- See /docs/storage-rls-setup.md for policy configuration details.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    '360ghar-storage',
    '360ghar-storage',
    FALSE,
    52428800,
    ARRAY[
        'image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif',
        'video/mp4', 'video/webm', 'video/quicktime', 'video/x-matroska', 'video/ogg',
        'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/ogg', 'audio/webm', 'audio/aac', 'audio/mp4',
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]::text[]
)
ON CONFLICT (id) DO UPDATE SET
    public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;
