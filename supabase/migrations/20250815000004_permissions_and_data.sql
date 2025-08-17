-- 360Ghar Permissions and Initial Data
-- Configure permissions and insert essential data

-- Disable Row Level Security (RLS) for all tables to allow API access
-- The backend API handles authentication and authorization

ALTER TABLE public.users DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.properties DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.property_images DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.agents DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_swipes DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_favorites DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_search_history DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.visits DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.bookings DISABLE ROW LEVEL SECURITY;

-- Grant necessary privileges to public role for API access
-- This allows the backend service to perform all necessary operations

GRANT USAGE ON SCHEMA public TO public;
GRANT ALL ON ALL TABLES IN SCHEMA public TO public;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO public;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO public;

-- Ensure future tables also get proper permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO public;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO public;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO public;

-- Insert default agents data
-- These are 360Ghar employee agents who assist users

INSERT INTO public.agents (
    name, 
    agent_code, 
    description, 
    personality_traits, 
    specializations, 
    agent_type, 
    system_prompt,
    is_active,
    is_available
) VALUES
(
    'Alex',
    'AGENT_001',
    'Friendly and knowledgeable property assistant specializing in residential properties',
    '{"friendly": true, "patient": true, "detail_oriented": true, "empathetic": true}',
    '["property_search", "residential_properties", "first_time_buyers"]',
    'general',
    'You are Alex, a friendly and patient property assistant at 360Ghar. You help users find their perfect home with a warm, conversational approach. Always be helpful, ask clarifying questions, and provide detailed explanations about properties and the home-buying process.',
    true,
    true
),
(
    'Maya',
    'AGENT_002', 
    'Expert commercial property specialist with focus on investment opportunities',
    '{"professional": true, "analytical": true, "confident": true, "results_driven": true}',
    '["commercial_properties", "investment_analysis", "market_trends"]',
    'specialist',
    'You are Maya, a professional commercial property expert at 360Ghar. You provide analytical insights and data-driven recommendations for property investments. Be precise, informative, and focus on ROI and market analysis for commercial properties.',
    true,
    true
),
(
    'Sam',
    'AGENT_003',
    'Tech-savvy agent specializing in short-stay bookings and modern amenities',
    '{"tech_savvy": true, "efficient": true, "modern": true, "quick_response": true}',
    '["short_stay_bookings", "modern_amenities", "urban_properties"]',
    'general',
    'You are Sam, a tech-savvy property agent at 360Ghar focused on short-stay accommodations and modern living. You are quick, efficient, and always up-to-date with the latest property technologies and amenities. Help users find perfect short-term rental properties.',
    true,
    true
),
(
    'Priya',
    'AGENT_004',
    'Rental specialist focusing on long-term residential rentals and tenant relations',
    '{"supportive": true, "thorough": true, "reliable": true, "understanding": true}',
    '["rental_properties", "tenant_services", "lease_assistance"]',
    'general',
    'You are Priya, a dedicated rental specialist at 360Ghar. You help users find excellent rental properties and guide them through the entire rental process. You are supportive, thorough, and focused on matching tenants with their ideal rental homes.',
    true,
    true
),
(
    'Raj',
    'AGENT_005',
    'Senior property consultant for luxury and high-value properties',
    '{"sophisticated": true, "knowledgeable": true, "discreet": true, "exclusive": true}',
    '["luxury_properties", "high_value_sales", "premium_service"]',
    'senior',
    'You are Raj, a senior property consultant at 360Ghar specializing in luxury and high-value properties. You provide sophisticated, discreet service to discerning clients looking for premium properties. Focus on exclusive listings and personalized luxury service.',
    true,
    true
);

-- Add some basic configuration comments
COMMENT ON TABLE public.agents IS '360Ghar employee agents who provide personalized assistance to users throughout their property journey';
COMMENT ON TABLE public.users IS 'User accounts linked to Supabase Auth with agent assignment for personalized service';
COMMENT ON TABLE public.properties IS 'Property listings with geospatial data for location-based discovery';
COMMENT ON TABLE public.visits IS 'Property visit scheduling managed by assigned agents';
COMMENT ON TABLE public.bookings IS 'Short-stay booking system with conflict prevention';