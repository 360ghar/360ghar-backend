"""Create complete property structure with lat/lng

Revision ID: f123456789ab
Revises: 
Create Date: 2025-07-20 16:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f123456789ab'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create all tables from scratch with new structure
    
    # Create enum types if they don't exist
    connection = op.get_bind()
    
    # Check and create enums
    try:
        connection.execute(sa.text("CREATE TYPE propertytype AS ENUM ('house', 'apartment', 'builder_floor', 'room')"))
    except Exception:
        pass
    
    try:
        connection.execute(sa.text("CREATE TYPE propertypurpose AS ENUM ('buy', 'rent', 'short_stay')"))
    except Exception:
        pass
        
    try:
        connection.execute(sa.text("CREATE TYPE propertystatus AS ENUM ('available', 'sold', 'rented', 'under_offer', 'maintenance')"))
    except Exception:
        pass
        
    try:
        connection.execute(sa.text("CREATE TYPE visitstatus AS ENUM ('scheduled', 'confirmed', 'completed', 'cancelled', 'rescheduled')"))
    except Exception:
        pass
        
    try:
        connection.execute(sa.text("CREATE TYPE bookingstatus AS ENUM ('pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed')"))
    except Exception:
        pass
        
    try:
        connection.execute(sa.text("CREATE TYPE paymentstatus AS ENUM ('pending', 'partial', 'paid', 'refunded', 'failed')"))
    except Exception:
        pass
    
    # Create users table
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('supabase_user_id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column('profile_image_url', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.Column('is_verified', sa.Boolean(), nullable=True, default=False),
        sa.Column('preferences', sa.JSON(), nullable=True),
        sa.Column('current_latitude', sa.String(), nullable=True),
        sa.Column('current_longitude', sa.String(), nullable=True),
        sa.Column('preferred_locations', sa.JSON(), nullable=True),
        sa.Column('notification_settings', sa.JSON(), nullable=True),
        sa.Column('privacy_settings', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_phone', 'users', ['phone'], unique=True) 
    op.create_index('ix_users_supabase_user_id', 'users', ['supabase_user_id'], unique=True)
    
    # Create relationship managers table
    op.create_table('relationship_managers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=False),
        sa.Column('whatsapp_number', sa.String(), nullable=True),
        sa.Column('profile_image_url', sa.String(), nullable=True),
        sa.Column('bio', sa.Text(), nullable=True),
        sa.Column('employee_id', sa.String(), nullable=True),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('experience_years', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.Column('working_hours', sa.String(), nullable=True),
        sa.Column('total_visits_handled', sa.Integer(), nullable=True, default=0),
        sa.Column('customer_rating', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('employee_id')
    )
    
    # Create properties table with direct lat/lng storage
    op.create_table('properties',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('property_type', sa.Enum('house', 'apartment', 'builder_floor', 'room', name='propertytype', create_type=False), nullable=False),
        sa.Column('purpose', sa.Enum('buy', 'rent', 'short_stay', name='propertypurpose', create_type=False), nullable=False),
        sa.Column('status', sa.Enum('available', 'sold', 'rented', 'under_offer', 'maintenance', name='propertystatus', create_type=False), nullable=True, default='available'),
        
        # Location data stored directly in property
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('state', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=False, default='India'),
        sa.Column('pincode', sa.String(), nullable=True),
        sa.Column('locality', sa.String(), nullable=True),
        sa.Column('sub_locality', sa.String(), nullable=True),
        sa.Column('landmark', sa.String(), nullable=True),
        sa.Column('full_address', sa.Text(), nullable=True),
        sa.Column('area_type', sa.String(), nullable=True),
        
        # Pricing
        sa.Column('base_price', sa.Float(), nullable=False),
        sa.Column('price_per_sqft', sa.Float(), nullable=True),
        sa.Column('monthly_rent', sa.Float(), nullable=True),
        sa.Column('daily_rate', sa.Float(), nullable=True),
        sa.Column('security_deposit', sa.Float(), nullable=True),
        sa.Column('maintenance_charges', sa.Float(), nullable=True),
        
        # Property details
        sa.Column('area_sqft', sa.Float(), nullable=True),
        sa.Column('bedrooms', sa.Integer(), nullable=True),
        sa.Column('bathrooms', sa.Integer(), nullable=True),
        sa.Column('balconies', sa.Integer(), nullable=True),
        sa.Column('parking_spaces', sa.Integer(), nullable=True),
        sa.Column('floor_number', sa.Integer(), nullable=True),
        sa.Column('total_floors', sa.Integer(), nullable=True),
        sa.Column('age_of_property', sa.Integer(), nullable=True),
        
        # For short stay properties
        sa.Column('max_occupancy', sa.Integer(), nullable=True),
        sa.Column('minimum_stay_days', sa.Integer(), nullable=True, default=1),
        
        # Amenities and features
        sa.Column('amenities', sa.JSON(), nullable=True),
        sa.Column('features', sa.JSON(), nullable=True),
        
        # Media
        sa.Column('main_image_url', sa.String(), nullable=True),
        sa.Column('virtual_tour_url', sa.String(), nullable=True),
        
        # Availability and booking
        sa.Column('is_available', sa.Boolean(), nullable=True, default=True),
        sa.Column('available_from', sa.String(), nullable=True),
        sa.Column('calendar_data', sa.JSON(), nullable=True),
        
        # SEO and search
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('search_keywords', sa.Text(), nullable=True),
        
        # Owner/Builder information
        sa.Column('owner_name', sa.String(), nullable=True),
        sa.Column('owner_contact', sa.String(), nullable=True),
        sa.Column('builder_name', sa.String(), nullable=True),
        
        # Performance metrics
        sa.Column('view_count', sa.Integer(), nullable=True, default=0),
        sa.Column('like_count', sa.Integer(), nullable=True, default=0),
        sa.Column('interest_count', sa.Integer(), nullable=True, default=0),
        
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for efficient location-based queries
    op.create_index('ix_properties_latitude', 'properties', ['latitude'])
    op.create_index('ix_properties_longitude', 'properties', ['longitude'])
    op.create_index('ix_properties_city', 'properties', ['city'])
    op.create_index('ix_properties_pincode', 'properties', ['pincode'])
    
    # Create property images table
    op.create_table('property_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('image_url', sa.String(), nullable=False),
        sa.Column('caption', sa.String(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True, default=0),
        sa.Column('is_main_image', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create user interaction tables
    op.create_table('user_swipes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('is_liked', sa.Boolean(), nullable=False),
        sa.Column('swipe_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('user_location_lat', sa.String(), nullable=True),
        sa.Column('user_location_lng', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('user_favorites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('is_favorite', sa.Boolean(), nullable=True, default=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('user_search_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('search_query', sa.String(), nullable=True),
        sa.Column('search_filters', sa.JSON(), nullable=True),
        sa.Column('search_location', sa.String(), nullable=True),
        sa.Column('search_radius', sa.Integer(), nullable=True),
        sa.Column('results_count', sa.Integer(), nullable=True),
        sa.Column('user_location_lat', sa.String(), nullable=True),
        sa.Column('user_location_lng', sa.String(), nullable=True),
        sa.Column('search_type', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create visits table
    op.create_table('visits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('relationship_manager_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_date', sa.DateTime(), nullable=False),
        sa.Column('actual_date', sa.DateTime(), nullable=True),
        sa.Column('status', sa.Enum('scheduled', 'confirmed', 'completed', 'cancelled', 'rescheduled', name='visitstatus', create_type=False), nullable=True, default='scheduled'),
        sa.Column('visitor_name', sa.String(), nullable=False),
        sa.Column('visitor_phone', sa.String(), nullable=False),
        sa.Column('visitor_email', sa.String(), nullable=True),
        sa.Column('number_of_visitors', sa.Integer(), nullable=True, default=1),
        sa.Column('preferred_time_slot', sa.String(), nullable=True),
        sa.Column('special_requirements', sa.Text(), nullable=True),
        sa.Column('visit_notes', sa.Text(), nullable=True),
        sa.Column('visitor_feedback', sa.Text(), nullable=True),
        sa.Column('interest_level', sa.String(), nullable=True),
        sa.Column('follow_up_required', sa.Boolean(), nullable=True, default=False),
        sa.Column('follow_up_date', sa.DateTime(), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('rescheduled_from', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['relationship_manager_id'], ['relationship_managers.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create bookings table
    op.create_table('bookings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=False),
        sa.Column('booking_reference', sa.String(), nullable=False),
        sa.Column('check_in_date', sa.DateTime(), nullable=False),
        sa.Column('check_out_date', sa.DateTime(), nullable=False),
        sa.Column('nights', sa.Integer(), nullable=False),
        sa.Column('guests', sa.Integer(), nullable=False),
        sa.Column('base_amount', sa.Float(), nullable=False),
        sa.Column('taxes_amount', sa.Float(), nullable=True),
        sa.Column('service_charges', sa.Float(), nullable=True),
        sa.Column('discount_amount', sa.Float(), nullable=True),
        sa.Column('total_amount', sa.Float(), nullable=False),
        sa.Column('booking_status', sa.Enum('pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'completed', name='bookingstatus', create_type=False), nullable=True, default='pending'),
        sa.Column('payment_status', sa.Enum('pending', 'partial', 'paid', 'refunded', 'failed', name='paymentstatus', create_type=False), nullable=True, default='pending'),
        sa.Column('primary_guest_name', sa.String(), nullable=False),
        sa.Column('primary_guest_phone', sa.String(), nullable=False),
        sa.Column('primary_guest_email', sa.String(), nullable=False),
        sa.Column('guest_details', sa.JSON(), nullable=True),
        sa.Column('special_requests', sa.Text(), nullable=True),
        sa.Column('internal_notes', sa.Text(), nullable=True),
        sa.Column('actual_check_in', sa.DateTime(), nullable=True),
        sa.Column('actual_check_out', sa.DateTime(), nullable=True),
        sa.Column('early_check_in', sa.Boolean(), nullable=True, default=False),
        sa.Column('late_check_out', sa.Boolean(), nullable=True, default=False),
        sa.Column('cancellation_date', sa.DateTime(), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('refund_amount', sa.Float(), nullable=True),
        sa.Column('payment_method', sa.String(), nullable=True),
        sa.Column('transaction_id', sa.String(), nullable=True),
        sa.Column('payment_date', sa.DateTime(), nullable=True),
        sa.Column('guest_rating', sa.Integer(), nullable=True),
        sa.Column('guest_review', sa.Text(), nullable=True),
        sa.Column('host_rating', sa.Integer(), nullable=True),
        sa.Column('host_review', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('booking_reference')
    )


def downgrade() -> None:
    # Drop all tables
    op.drop_table('bookings')
    op.drop_table('visits')
    op.drop_table('user_search_history')
    op.drop_table('user_favorites')
    op.drop_table('user_swipes')
    op.drop_table('property_images')
    op.drop_table('properties')
    op.drop_table('relationship_managers')
    op.drop_table('users')