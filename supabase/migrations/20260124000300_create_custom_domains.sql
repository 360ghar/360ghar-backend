-- Create custom_domains table for branded tour URLs
-- Migration: 20260124000300_create_custom_domains.sql

CREATE TABLE IF NOT EXISTS custom_domains (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain VARCHAR(255) NOT NULL UNIQUE,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    ssl_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    verification_token VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_custom_domains_user_id ON custom_domains(user_id);
CREATE INDEX IF NOT EXISTS idx_custom_domains_domain ON custom_domains(domain);
CREATE INDEX IF NOT EXISTS idx_custom_domains_verification_status ON custom_domains(verification_status);

-- Add comments for documentation
COMMENT ON TABLE custom_domains IS 'Custom domains for branded tour URLs';
COMMENT ON COLUMN custom_domains.verification_status IS 'Domain verification status: pending, verified, failed';
COMMENT ON COLUMN custom_domains.ssl_status IS 'SSL certificate status: pending, provisioning, active, failed';
COMMENT ON COLUMN custom_domains.verification_token IS 'Token to be added as DNS TXT record for verification';
