-- 360Ghar Indexes and Performance Optimizations
-- Create indexes, constraints, and performance optimizations

-- Users table indexes
CREATE INDEX idx_users_supabase_user_id ON public.users(supabase_user_id);
CREATE INDEX idx_users_email ON public.users(email);
CREATE INDEX idx_users_phone ON public.users(phone);
CREATE INDEX idx_users_is_active ON public.users(is_active);
CREATE INDEX idx_users_agent_id ON public.users(agent_id);
CREATE INDEX idx_users_location ON public.users(current_latitude, current_longitude);

-- Properties table indexes
CREATE INDEX idx_properties_property_type ON public.properties(property_type);
CREATE INDEX idx_properties_purpose ON public.properties(purpose);
CREATE INDEX idx_properties_status ON public.properties(status);
CREATE INDEX idx_properties_city ON public.properties(city);
CREATE INDEX idx_properties_locality ON public.properties(locality);
CREATE INDEX idx_properties_is_available ON public.properties(is_available);
CREATE INDEX idx_properties_location ON public.properties(latitude, longitude);
CREATE INDEX idx_properties_base_price ON public.properties(base_price);
CREATE INDEX idx_properties_bedrooms ON public.properties(bedrooms);
CREATE INDEX idx_properties_bathrooms ON public.properties(bathrooms);
CREATE INDEX idx_properties_area_sqft ON public.properties(area_sqft);
CREATE INDEX idx_properties_created_at ON public.properties(created_at);
CREATE INDEX idx_properties_view_count ON public.properties(view_count);

-- Composite indexes for property filtering
CREATE INDEX idx_properties_type_purpose_city ON public.properties(property_type, purpose, city);
CREATE INDEX idx_properties_type_bedrooms_price ON public.properties(property_type, bedrooms, base_price);
CREATE INDEX idx_properties_available_city_type ON public.properties(is_available, city, property_type);

-- PostGIS spatial indexes for efficient geospatial queries
CREATE INDEX idx_properties_location_gist ON public.properties USING GIST (
    ST_MakePoint(longitude, latitude)
) WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Property images indexes
CREATE INDEX idx_property_images_property_id ON public.property_images(property_id);
CREATE INDEX idx_property_images_is_main ON public.property_images(is_main_image);
CREATE INDEX idx_property_images_display_order ON public.property_images(property_id, display_order);

-- Agents table indexes
CREATE INDEX idx_agents_agent_code ON public.agents(agent_code);
CREATE INDEX idx_agents_is_active ON public.agents(is_active);
CREATE INDEX idx_agents_is_available ON public.agents(is_available);
CREATE INDEX idx_agents_agent_type ON public.agents(agent_type);
CREATE INDEX idx_agents_total_users_assigned ON public.agents(total_users_assigned);
CREATE INDEX idx_agents_last_active_at ON public.agents(last_active_at);

-- User swipes indexes
CREATE INDEX idx_user_swipes_user_id ON public.user_swipes(user_id);
CREATE INDEX idx_user_swipes_property_id ON public.user_swipes(property_id);
CREATE INDEX idx_user_swipes_is_liked ON public.user_swipes(is_liked);
CREATE INDEX idx_user_swipes_timestamp ON public.user_swipes(swipe_timestamp);
CREATE INDEX idx_user_swipes_session ON public.user_swipes(session_id);

-- Composite index for swipe analytics
CREATE INDEX idx_user_swipes_user_liked ON public.user_swipes(user_id, is_liked);

-- User favorites indexes
CREATE INDEX idx_user_favorites_user_id ON public.user_favorites(user_id);
CREATE INDEX idx_user_favorites_property_id ON public.user_favorites(property_id);
CREATE INDEX idx_user_favorites_is_favorite ON public.user_favorites(is_favorite);

-- User search history indexes
CREATE INDEX idx_user_search_history_user_id ON public.user_search_history(user_id);
CREATE INDEX idx_user_search_history_search_type ON public.user_search_history(search_type);
CREATE INDEX idx_user_search_history_created_at ON public.user_search_history(created_at);
CREATE INDEX idx_user_search_history_session ON public.user_search_history(session_id);

-- Visits table indexes
CREATE INDEX idx_visits_user_id ON public.visits(user_id);
CREATE INDEX idx_visits_property_id ON public.visits(property_id);
CREATE INDEX idx_visits_agent_id ON public.visits(agent_id);
CREATE INDEX idx_visits_status ON public.visits(status);
CREATE INDEX idx_visits_scheduled_date ON public.visits(scheduled_date);
CREATE INDEX idx_visits_follow_up ON public.visits(follow_up_required, follow_up_date);

-- Composite indexes for visit management
CREATE INDEX idx_visits_agent_date ON public.visits(agent_id, scheduled_date);
CREATE INDEX idx_visits_user_status ON public.visits(user_id, status);

-- Bookings table indexes
CREATE INDEX idx_bookings_user_id ON public.bookings(user_id);
CREATE INDEX idx_bookings_property_id ON public.bookings(property_id);
CREATE INDEX idx_bookings_booking_reference ON public.bookings(booking_reference);
CREATE INDEX idx_bookings_booking_status ON public.bookings(booking_status);
CREATE INDEX idx_bookings_payment_status ON public.bookings(payment_status);
CREATE INDEX idx_bookings_check_in_date ON public.bookings(check_in_date);
CREATE INDEX idx_bookings_check_out_date ON public.bookings(check_out_date);
CREATE INDEX idx_bookings_created_at ON public.bookings(created_at);

-- Composite indexes for booking availability checks
CREATE INDEX idx_bookings_property_dates ON public.bookings(property_id, check_in_date, check_out_date);
CREATE INDEX idx_bookings_property_status_dates ON public.bookings(property_id, booking_status, check_in_date, check_out_date);

-- Additional constraints for data integrity

-- Ensure property coordinates are valid when provided
ALTER TABLE public.properties 
ADD CONSTRAINT chk_properties_latitude 
CHECK (latitude IS NULL OR (latitude >= -90 AND latitude <= 90));

ALTER TABLE public.properties 
ADD CONSTRAINT chk_properties_longitude 
CHECK (longitude IS NULL OR (longitude >= -180 AND longitude <= 180));

-- Ensure both latitude and longitude are provided together for geospatial queries
ALTER TABLE public.properties 
ADD CONSTRAINT chk_properties_coordinates_complete 
CHECK ((latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL));

-- Ensure positive values for property dimensions and pricing
ALTER TABLE public.properties 
ADD CONSTRAINT chk_properties_positive_price 
CHECK (base_price > 0);

ALTER TABLE public.properties 
ADD CONSTRAINT chk_properties_positive_area 
CHECK (area_sqft IS NULL OR area_sqft > 0);

ALTER TABLE public.properties 
ADD CONSTRAINT chk_properties_positive_rooms 
CHECK (bedrooms IS NULL OR bedrooms >= 0);

ALTER TABLE public.properties 
ADD CONSTRAINT chk_properties_positive_bathrooms 
CHECK (bathrooms IS NULL OR bathrooms >= 0);

-- Ensure check-out is after check-in for bookings
ALTER TABLE public.bookings 
ADD CONSTRAINT chk_bookings_dates_valid 
CHECK (check_out_date > check_in_date);

-- Ensure positive amounts for bookings
ALTER TABLE public.bookings 
ADD CONSTRAINT chk_bookings_positive_total 
CHECK (total_amount >= 0);

ALTER TABLE public.bookings 
ADD CONSTRAINT chk_bookings_positive_nights 
CHECK (nights > 0);

ALTER TABLE public.bookings 
ADD CONSTRAINT chk_bookings_positive_guests 
CHECK (guests > 0);

-- Ensure agent ratings are within valid range
ALTER TABLE public.agents 
ADD CONSTRAINT chk_agents_satisfaction_rating 
CHECK (user_satisfaction_rating >= 0.0 AND user_satisfaction_rating <= 5.0);

-- Ensure agent stats are non-negative
ALTER TABLE public.agents 
ADD CONSTRAINT chk_agents_positive_stats 
CHECK (total_users_assigned >= 0 AND total_interactions >= 0 AND average_response_time_seconds >= 0);