-- ============================================================
-- 360Ghar Schema — 05: Blog
-- ============================================================
-- blog_categories, blog_tags, blog_posts (with all SEO/status
-- fields from the start), blog_post_categories, blog_post_tags
-- ============================================================

CREATE TABLE blog_categories (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE UNIQUE INDEX ux_blog_categories_slug ON blog_categories (slug);
CREATE UNIQUE INDEX ux_blog_categories_name ON blog_categories (name);
CREATE TRIGGER update_blog_categories_updated_at
    BEFORE UPDATE ON blog_categories FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE blog_tags (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE UNIQUE INDEX ux_blog_tags_slug ON blog_tags (slug);
CREATE UNIQUE INDEX ux_blog_tags_name ON blog_tags (name);
CREATE TRIGGER update_blog_tags_updated_at
    BEFORE UPDATE ON blog_tags FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE blog_posts (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    content TEXT NOT NULL,
    excerpt TEXT,
    cover_image_url VARCHAR,

    -- Publication state
    active BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR DEFAULT 'draft',
    scheduled_at TIMESTAMPTZ,
    preview_token VARCHAR,

    -- SEO fields
    meta_title VARCHAR(60),
    meta_description VARCHAR(160),
    focus_keyword VARCHAR(200),
    canonical_url VARCHAR(500),
    og_image_url VARCHAR(500),
    seo_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Reading analytics
    reading_time_minutes INTEGER,
    word_count INTEGER,

    -- Publishing timestamp
    published_at TIMESTAMPTZ,

    -- Structured sources
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,

    author_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE UNIQUE INDEX ux_blog_posts_slug ON blog_posts (slug);
CREATE INDEX ix_blog_posts_created_at ON blog_posts (created_at);
CREATE INDEX ix_blog_posts_active ON blog_posts (active);
CREATE INDEX idx_blog_posts_status ON blog_posts (status);
CREATE INDEX idx_blog_posts_published_at ON blog_posts (published_at);
CREATE INDEX ix_blog_posts_focus_keyword ON blog_posts (focus_keyword);
CREATE INDEX ix_blog_posts_seo_metadata ON blog_posts USING GIN (seo_metadata);
CREATE INDEX idx_blog_posts_preview_token ON blog_posts (preview_token) WHERE preview_token IS NOT NULL;
CREATE TRIGGER update_blog_posts_updated_at
    BEFORE UPDATE ON blog_posts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE blog_post_categories (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
    category_id BIGINT NOT NULL REFERENCES blog_categories(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);
CREATE UNIQUE INDEX ux_blog_post_category_unique ON blog_post_categories (post_id, category_id);

CREATE TABLE blog_post_tags (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES blog_posts(id) ON DELETE CASCADE,
    tag_id BIGINT NOT NULL REFERENCES blog_tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);
CREATE UNIQUE INDEX ux_blog_post_tag_unique ON blog_post_tags (post_id, tag_id);
