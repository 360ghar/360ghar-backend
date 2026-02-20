-- Create agent_interactions table for tracking agent-user interactions
-- Migration: 20260124000200_create_agent_interactions.sql

CREATE TABLE IF NOT EXISTS agent_interactions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    response TEXT,
    response_time_seconds INTEGER,
    user_satisfaction INTEGER CHECK (user_satisfaction >= 1 AND user_satisfaction <= 5),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_agent_interactions_agent_id ON agent_interactions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_interactions_user_id ON agent_interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_interactions_created_at ON agent_interactions(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_interactions_agent_created ON agent_interactions(agent_id, created_at);

-- Add comments for documentation
COMMENT ON TABLE agent_interactions IS 'Tracks all interactions between agents and users for analytics';
COMMENT ON COLUMN agent_interactions.interaction_type IS 'Type of interaction: chat, call, email, etc.';
COMMENT ON COLUMN agent_interactions.response_time_seconds IS 'Time taken by agent to respond in seconds';
COMMENT ON COLUMN agent_interactions.user_satisfaction IS 'User satisfaction rating 1-5';
