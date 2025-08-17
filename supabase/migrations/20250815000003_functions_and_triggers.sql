-- 360Ghar Essential Functions and Triggers
-- Only includes functions that are actually used in the codebase

-- Trigger function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Agent assignment functions (used by the application)

-- Get the next available agent for assignment (load balancing)
CREATE OR REPLACE FUNCTION get_next_available_agent()
RETURNS BIGINT AS $$
DECLARE
    agent_id BIGINT;
BEGIN
    -- Get the agent with the least users assigned (load balancing)
    SELECT id INTO agent_id
    FROM agents a
    WHERE a.is_active = true AND a.is_available = true
    ORDER BY a.total_users_assigned ASC, a.last_active_at ASC NULLS FIRST
    LIMIT 1;
    
    RETURN agent_id;
END;
$$ LANGUAGE plpgsql;

-- Assign an agent to a user if they don't have one
CREATE OR REPLACE FUNCTION assign_agent_to_user_if_needed(p_user_id BIGINT)
RETURNS BIGINT AS $$
DECLARE
    user_agent_id BIGINT;
    assigned_agent_id BIGINT;
BEGIN
    -- Check if user already has an agent
    SELECT agent_id INTO user_agent_id
    FROM users
    WHERE id = p_user_id;
    
    IF user_agent_id IS NOT NULL THEN
        RETURN user_agent_id;
    END IF;
    
    -- Get next available agent
    SELECT get_next_available_agent() INTO assigned_agent_id;
    
    IF assigned_agent_id IS NULL THEN
        RETURN NULL;
    END IF;
    
    -- Assign agent to user
    UPDATE users 
    SET agent_id = assigned_agent_id,
        updated_at = NOW()
    WHERE id = p_user_id;
    
    -- Update agent stats
    UPDATE agents 
    SET total_users_assigned = total_users_assigned + 1,
        last_active_at = NOW(),
        updated_at = NOW()
    WHERE id = assigned_agent_id;
    
    RETURN assigned_agent_id;
END;
$$ LANGUAGE plpgsql;

-- Create a visit with automatic agent assignment
CREATE OR REPLACE FUNCTION create_visit_with_agent_assignment(
    p_user_id BIGINT,
    p_property_id BIGINT,
    p_scheduled_date TIMESTAMPTZ,
    p_special_requirements TEXT DEFAULT NULL
)
RETURNS BIGINT AS $$
DECLARE
    assigned_agent_id BIGINT;
    visit_id BIGINT;
BEGIN
    -- Ensure user has an agent assigned
    SELECT assign_agent_to_user_if_needed(p_user_id) INTO assigned_agent_id;
    
    IF assigned_agent_id IS NULL THEN
        RAISE EXCEPTION 'No agents available for assignment';
    END IF;
    
    -- Create the visit with agent assignment
    INSERT INTO visits (
        user_id, property_id, agent_id, scheduled_date,
        status, special_requirements,
        follow_up_required, created_at, updated_at
    ) VALUES (
        p_user_id, p_property_id, assigned_agent_id, p_scheduled_date,
        'scheduled', p_special_requirements,
        false, NOW(), NOW()
    )
    RETURNING id INTO visit_id;
    
    -- Update agent interaction count
    UPDATE agents 
    SET total_interactions = total_interactions + 1,
        last_active_at = NOW(),
        updated_at = NOW()
    WHERE id = assigned_agent_id;
    
    RETURN visit_id;
END;
$$ LANGUAGE plpgsql;

-- Create updated_at triggers for all tables

-- Users table trigger
CREATE TRIGGER set_timestamp_users
    BEFORE UPDATE ON public.users
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- Properties table trigger
CREATE TRIGGER set_timestamp_properties
    BEFORE UPDATE ON public.properties
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- Property images table trigger
CREATE TRIGGER set_timestamp_property_images
    BEFORE UPDATE ON public.property_images
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- Agents table trigger
CREATE TRIGGER set_timestamp_agents
    BEFORE UPDATE ON public.agents
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- User swipes table trigger
CREATE TRIGGER set_timestamp_user_swipes
    BEFORE UPDATE ON public.user_swipes
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- User favorites table trigger
CREATE TRIGGER set_timestamp_user_favorites
    BEFORE UPDATE ON public.user_favorites
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- User search history table trigger
CREATE TRIGGER set_timestamp_user_search_history
    BEFORE UPDATE ON public.user_search_history
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- Visits table trigger
CREATE TRIGGER set_timestamp_visits
    BEFORE UPDATE ON public.visits
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();

-- Bookings table trigger
CREATE TRIGGER set_timestamp_bookings
    BEFORE UPDATE ON public.bookings
    FOR EACH ROW
    EXECUTE FUNCTION trigger_set_timestamp();