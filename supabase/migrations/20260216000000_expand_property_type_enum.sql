-- Expand property_type enum to align backend and app contract.
ALTER TYPE property_type ADD VALUE IF NOT EXISTS 'villa';
ALTER TYPE property_type ADD VALUE IF NOT EXISTS 'plot';
ALTER TYPE property_type ADD VALUE IF NOT EXISTS 'condo';
ALTER TYPE property_type ADD VALUE IF NOT EXISTS 'penthouse';
ALTER TYPE property_type ADD VALUE IF NOT EXISTS 'studio';
ALTER TYPE property_type ADD VALUE IF NOT EXISTS 'loft';
