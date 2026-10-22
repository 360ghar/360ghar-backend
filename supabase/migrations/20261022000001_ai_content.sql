-- =============================================================================
-- AI content: grounded text blocks and generated image registry
-- Migration: 20261022000001_ai_content.sql
--
-- content_blocks holds generated, validated text per (entity_type, slug, locale):
-- locality pages and property summaries. The API serves rows whose review_status
-- is 'auto' or 'approved'. indexable tells the website whether the page may be
-- indexed (enough verified facts). facts_hash makes the nightly run idempotent.
-- generated_images is the registry for house-style art and OG cards (Phase 3).
-- Additive only. The API connects with the service role; block direct client access.
-- =============================================================================

CREATE TABLE IF NOT EXISTS content_blocks (
    id             BIGSERIAL PRIMARY KEY,
    entity_type    VARCHAR(20)  NOT NULL,
    slug           VARCHAR(200) NOT NULL,
    locale         VARCHAR(5)   NOT NULL,
    body           JSONB        NOT NULL,
    sources        JSONB        NOT NULL DEFAULT '[]'::jsonb,
    facts_hash     VARCHAR(64)  NOT NULL,
    fact_count     INTEGER      NOT NULL DEFAULT 0,
    key_fact       BOOLEAN      NOT NULL DEFAULT false,
    model          VARCHAR(100),
    prompt_version VARCHAR(20)  NOT NULL,
    generated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    data_as_of     DATE,
    review_status  VARCHAR(20)  NOT NULL DEFAULT 'needs_review',
    indexable      BOOLEAN      NOT NULL DEFAULT false,
    dup_score      DOUBLE PRECISION,
    errors         JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT content_blocks_entity_type_check CHECK (entity_type IN ('locality', 'property')),
    CONSTRAINT content_blocks_locale_check CHECK (locale IN ('en', 'hi')),
    CONSTRAINT content_blocks_review_status_check
        CHECK (review_status IN ('auto', 'needs_review', 'approved', 'rejected', 'failed'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_content_blocks_entity
    ON content_blocks (entity_type, slug, locale);
CREATE INDEX IF NOT EXISTS ix_content_blocks_review
    ON content_blocks (entity_type, review_status);
CREATE INDEX IF NOT EXISTS ix_content_blocks_manifest
    ON content_blocks (entity_type, updated_at DESC)
    WHERE review_status IN ('auto', 'approved');

-- Locality master data. Loaded once from a committed JSON snapshot by
-- scripts/import_localities.py. The backend never reads the website repo.
CREATE TABLE IF NOT EXISTS localities (
    slug        VARCHAR(200) PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    city        VARCHAR(100) NOT NULL,
    place_type  VARCHAR(30)  NOT NULL,
    parent_slug VARCHAR(200),
    aliases     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    landmarks   JSONB        NOT NULL DEFAULT '[]'::jsonb,
    source      VARCHAR(100),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT localities_place_type_check
        CHECK (place_type IN ('locality', 'sector', 'society', 'village', 'road', 'township', 'phase'))
);

CREATE INDEX IF NOT EXISTS ix_localities_city ON localities (city);

CREATE TABLE IF NOT EXISTS generated_images (
    key          VARCHAR(64) PRIMARY KEY,
    subject_type VARCHAR(20)  NOT NULL,
    subject_slug VARCHAR(200) NOT NULL,
    public_id    VARCHAR(300),
    url          TEXT,
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending',
    retry_after  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT generated_images_subject_type_check
        CHECK (subject_type IN ('city', 'locality', 'property', 'blog')),
    CONSTRAINT generated_images_status_check
        CHECK (status IN ('pending', 'ready', 'failed'))
);

CREATE INDEX IF NOT EXISTS ix_generated_images_subject
    ON generated_images (subject_type, subject_slug);
CREATE INDEX IF NOT EXISTS ix_generated_images_retry
    ON generated_images (retry_after)
    WHERE status = 'failed';

-- content_blocks.updated_at is set by the application on purpose: the manifest serves it as the
-- page's last-modified date, so a bookkeeping write (a failure note) must not move it.
DROP TRIGGER IF EXISTS update_localities_updated_at ON localities;
CREATE TRIGGER update_localities_updated_at
    BEFORE UPDATE ON localities FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
DROP TRIGGER IF EXISTS update_generated_images_updated_at ON generated_images;
CREATE TRIGGER update_generated_images_updated_at
    BEFORE UPDATE ON generated_images FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE content_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE generated_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE localities ENABLE ROW LEVEL SECURITY;
