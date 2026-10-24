-- Additive data-hub provenance storage. Existing rows remain unchecked/unverified.
ALTER TABLE rera_projects
    ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_successful_run_id INTEGER
        REFERENCES scraper_runs(id) ON DELETE SET NULL;

ALTER TABLE zoning_data
    ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_successful_run_id INTEGER
        REFERENCES scraper_runs(id) ON DELETE SET NULL;

ALTER TABLE colony_approvals
    ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_successful_run_id INTEGER
        REFERENCES scraper_runs(id) ON DELETE SET NULL;

CREATE TABLE source_documents (
    id BIGSERIAL PRIMARY KEY,
    authority TEXT NOT NULL,
    title TEXT NOT NULL,
    canonical_url TEXT,
    source_record_id TEXT,
    jurisdiction TEXT NOT NULL,
    document_type VARCHAR(100) NOT NULL,
    language VARCHAR(20) NOT NULL,
    license_name TEXT,
    reuse_terms TEXT,
    terms_url TEXT,
    published_at DATE,
    effective_from DATE,
    effective_to DATE,
    fetched_at TIMESTAMPTZ NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    artifact_reference TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_source_documents_has_locator
        CHECK (
            NULLIF(BTRIM(canonical_url), '') IS NOT NULL
            OR NULLIF(BTRIM(source_record_id), '') IS NOT NULL
        ),
    CONSTRAINT ck_source_documents_effective_dates
        CHECK (effective_from IS NULL OR effective_to IS NULL OR effective_from <= effective_to),
    CONSTRAINT ck_source_documents_sha256
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX uq_source_documents_url_hash
    ON source_documents (canonical_url, content_sha256)
    WHERE canonical_url IS NOT NULL;
CREATE UNIQUE INDEX uq_source_documents_record_hash
    ON source_documents (authority, source_record_id, content_sha256)
    WHERE source_record_id IS NOT NULL;

CREATE TABLE data_hub_evidence_assertions (
    id BIGSERIAL PRIMARY KEY,
    rera_project_id INTEGER REFERENCES rera_projects(id) ON DELETE RESTRICT,
    zoning_data_id INTEGER REFERENCES zoning_data(id) ON DELETE RESTRICT,
    colony_approval_id INTEGER REFERENCES colony_approvals(id) ON DELETE RESTRICT,
    field_path VARCHAR(120) NOT NULL,
    normalized_value JSONB NOT NULL,
    unit VARCHAR(50),
    source_document_id BIGINT NOT NULL
        REFERENCES source_documents(id) ON DELETE RESTRICT,
    locator_page INTEGER,
    locator_table INTEGER,
    locator_row INTEGER,
    locator_column INTEGER,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    reviewer_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    method VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'unreviewed',
    source_run_id INTEGER REFERENCES scraper_runs(id) ON DELETE SET NULL,
    supersedes_id BIGINT
        REFERENCES data_hub_evidence_assertions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_data_hub_assertions_exactly_one_target
        CHECK (num_nonnulls(rera_project_id, zoning_data_id, colony_approval_id) = 1),
    CONSTRAINT ck_data_hub_assertions_field_path CHECK (field_path IN (
        'rera_project.rera_number',
        'rera_project.project_name',
        'rera_project.developer_name',
        'rera_project.location',
        'rera_project.district',
        'rera_project.total_units',
        'rera_project.units_booked',
        'rera_project.possession_date',
        'rera_project.registration_date',
        'rera_project.expiry_date',
        'rera_project.status',
        'rera_project.project_type',
        'rera_project.total_area_sqm',
        'zoning_data.sector',
        'zoning_data.land_use',
        'zoning_data.far_limit',
        'zoning_data.max_height_m',
        'zoning_data.max_coverage_pct',
        'zoning_data.setback_front_m',
        'zoning_data.setback_rear_m',
        'zoning_data.master_plan_year',
        'zoning_data.notes',
        'colony_approval.colony_name',
        'colony_approval.developer_name',
        'colony_approval.district',
        'colony_approval.licence_number',
        'colony_approval.approval_status',
        'colony_approval.clu_status',
        'colony_approval.approval_date',
        'colony_approval.area_acres',
        'colony_approval.sector'
    )),
    CONSTRAINT ck_data_hub_assertions_status
        CHECK (status IN ('unreviewed', 'accepted', 'rejected', 'superseded')),
    CONSTRAINT ck_data_hub_assertions_method
        CHECK (method IN ('scrape', 'manual', 'ocr', 'derived')),
    CONSTRAINT ck_data_hub_assertions_locator_page
        CHECK (locator_page IS NULL OR locator_page > 0),
    CONSTRAINT ck_data_hub_assertions_locator_table
        CHECK (locator_table IS NULL OR locator_table > 0),
    CONSTRAINT ck_data_hub_assertions_locator_row
        CHECK (locator_row IS NULL OR locator_row > 0),
    CONSTRAINT ck_data_hub_assertions_locator_column
        CHECK (locator_column IS NULL OR locator_column > 0),
    CONSTRAINT ck_data_hub_assertions_validity_dates
        CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to)
);

CREATE UNIQUE INDEX uq_data_hub_assertions_rera_run_field_source
    ON data_hub_evidence_assertions
       (rera_project_id, source_run_id, field_path, source_document_id)
    WHERE rera_project_id IS NOT NULL;
CREATE UNIQUE INDEX uq_data_hub_assertions_zoning_run_field_source
    ON data_hub_evidence_assertions
       (zoning_data_id, source_run_id, field_path, source_document_id)
    WHERE zoning_data_id IS NOT NULL;
CREATE UNIQUE INDEX uq_data_hub_assertions_colony_run_field_source
    ON data_hub_evidence_assertions
       (colony_approval_id, source_run_id, field_path, source_document_id)
    WHERE colony_approval_id IS NOT NULL;

CREATE TABLE data_hub_entity_revisions (
    id BIGSERIAL PRIMARY KEY,
    rera_project_id INTEGER REFERENCES rera_projects(id) ON DELETE RESTRICT,
    zoning_data_id INTEGER REFERENCES zoning_data(id) ON DELETE RESTRICT,
    colony_approval_id INTEGER REFERENCES colony_approvals(id) ON DELETE RESTRICT,
    revision_number INTEGER NOT NULL,
    normalized_snapshot JSONB NOT NULL,
    snapshot_sha256 VARCHAR(64) NOT NULL,
    changed_fields JSONB NOT NULL,
    source_run_id INTEGER REFERENCES scraper_runs(id) ON DELETE RESTRICT,
    source_document_id BIGINT
        REFERENCES source_documents(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_data_hub_revisions_exactly_one_target
        CHECK (num_nonnulls(rera_project_id, zoning_data_id, colony_approval_id) = 1),
    CONSTRAINT ck_data_hub_revisions_positive_number
        CHECK (revision_number > 0),
    CONSTRAINT ck_data_hub_revisions_sha256
        CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_data_hub_revisions_snapshot_object
        CHECK (jsonb_typeof(normalized_snapshot) = 'object'),
    CONSTRAINT ck_data_hub_revisions_snapshot_allowlist CHECK (
        normalized_snapshot - ARRAY[
            'rera_number', 'project_name', 'developer_name', 'location', 'district',
            'total_units', 'units_booked', 'possession_date', 'registration_date',
            'expiry_date', 'status', 'project_type', 'total_area_sqm',
            'sector', 'land_use', 'far_limit', 'max_height_m', 'max_coverage_pct',
            'setback_front_m', 'setback_rear_m', 'master_plan_year', 'notes',
            'colony_name', 'licence_number', 'approval_status', 'clu_status',
            'approval_date', 'area_acres'
        ]::TEXT[] = '{}'::JSONB
    ),
    CONSTRAINT ck_data_hub_revisions_changed_fields_array
        CHECK (jsonb_typeof(changed_fields) = 'array')
);

CREATE UNIQUE INDEX uq_data_hub_revisions_rera_number
    ON data_hub_entity_revisions (rera_project_id, revision_number)
    WHERE rera_project_id IS NOT NULL;
CREATE UNIQUE INDEX uq_data_hub_revisions_zoning_number
    ON data_hub_entity_revisions (zoning_data_id, revision_number)
    WHERE zoning_data_id IS NOT NULL;
CREATE UNIQUE INDEX uq_data_hub_revisions_colony_number
    ON data_hub_entity_revisions (colony_approval_id, revision_number)
    WHERE colony_approval_id IS NOT NULL;

CREATE FUNCTION reject_data_hub_revision_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'data hub entity revisions are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_hub_entity_revisions_immutable
    BEFORE UPDATE OR DELETE ON data_hub_entity_revisions
    FOR EACH ROW EXECUTE FUNCTION reject_data_hub_revision_mutation();

ALTER TABLE source_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_hub_evidence_assertions ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_hub_entity_revisions ENABLE ROW LEVEL SECURITY;
