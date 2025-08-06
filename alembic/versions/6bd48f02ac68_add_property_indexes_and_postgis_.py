"""Add property indexes and PostGIS extensions

Revision ID: 6bd48f02ac68
Revises: f123456789ab
Create Date: 2025-08-06 06:02:10.290509

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6bd48f02ac68'
down_revision = 'f123456789ab'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable PostgreSQL extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS cube")
    op.execute("CREATE EXTENSION IF NOT EXISTS earthdistance")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    
    # Spatial index for location-based queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_location 
        ON properties USING GIST (ST_MakePoint(longitude::float, latitude::float))
    """)
    
    # Composite indexes for common filter combinations
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_search 
        ON properties (is_available, purpose, property_type, city, locality)
    """)
    
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_price_range 
        ON properties (base_price, is_available)
    """)
    
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_rooms 
        ON properties (bedrooms, bathrooms, is_available)
    """)
    
    # Full-text search index
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_fulltext 
        ON properties USING GIN (
            to_tsvector('english', 
                COALESCE(title, '') || ' ' || 
                COALESCE(description, '') || ' ' || 
                COALESCE(locality, '') || ' ' || 
                COALESCE(city, '')
            )
        )
    """)
    
    # Index for user swipes (already swiped properties)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_swipes_composite 
        ON user_swipes (user_id, property_id)
    """)
    
    # Index for property availability and created_at for sorting
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_availability_created 
        ON properties (is_available, created_at DESC)
    """)
    
    # Index for popularity sorting
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_popularity 
        ON properties (like_count DESC, view_count DESC)
    """)
    
    # Additional performance indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_type_purpose 
        ON properties (property_type, purpose, is_available)
    """)
    
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_properties_location_filters 
        ON properties (city, locality, pincode, is_available)
    """)


def downgrade() -> None:
    # Drop indexes in reverse order
    op.execute("DROP INDEX IF EXISTS idx_properties_location_filters")
    op.execute("DROP INDEX IF EXISTS idx_properties_type_purpose")
    op.execute("DROP INDEX IF EXISTS idx_properties_popularity")
    op.execute("DROP INDEX IF EXISTS idx_properties_availability_created")
    op.execute("DROP INDEX IF EXISTS idx_user_swipes_composite")
    op.execute("DROP INDEX IF EXISTS idx_properties_fulltext")
    op.execute("DROP INDEX IF EXISTS idx_properties_rooms")
    op.execute("DROP INDEX IF EXISTS idx_properties_price_range")
    op.execute("DROP INDEX IF EXISTS idx_properties_search")
    op.execute("DROP INDEX IF EXISTS idx_properties_location")
    
    # Note: We don't drop extensions as they might be used by other applications