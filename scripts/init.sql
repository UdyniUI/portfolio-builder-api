-- Initialize PortfolioOS database schema
-- This file runs automatically when PostgreSQL container starts

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    auth0_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    avatar_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Portfolios table
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    design_system_id INTEGER,
    template_id INTEGER,
    status VARCHAR(50) DEFAULT 'draft', -- draft, published, archived
    custom_domain VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DE    updated_at TIMESTAMP DE    updated_at TIMESTAMP DE    updated_at TIMESTAMP DE    updated_at TIMESTAMPRI    updated_at TIMESTAMP DE    updated_aT     updated_at TIMESTAMP DE    updated_at TIMESTAMP DE    updagn tokens as JSON
                                  us                         L,
    is_public BOOLEAN DEFAULT false,
    c    c    c    c    c    c    c RENT_TIME    c    c    c    c    cESTAMP DEFAULT CURRENT_TIMESTAMP    c    c    c o dat    c    c    c    c    c    c    c RENT_TIME    cTE    c    c    c    c    c    c    c RENT_TIME    AL PRI    c    
    portfo    portfo    portfo    portfo    pportf    portfo    portfo    pDE    portfo    portfo    portfo    portfo    pportf    portfo    por'e    portfo    portfo    portfoOT     portfo    portfo    portfo   re
    order_index INTEGER DEFAULT 0,
    created_at TIMESTAM    created_at TIMESTAM    created_at TIMESTAM    created_at TIMESTAT_    created_at TIMESTAM    creo_    created_at TIMESTAM    created_at TIMESTAM    E TABLE IF NOT EXISTS resume_uploads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_url TEXT NOT NULL,
    original_filename VARCHAR(255),
    extracted_data JSONB, -- Extracted resume data
    extraction_status VARCHAR(50) DEFAULT 'pending', -- pending, completed, failed
    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    E     created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D     DE    created_at TIMESTAMP D    creea    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    created_at TIMESTAMP D    _s    created_at TIMESTg);
CRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCliCRCRCRCRCRCRCRCRCRX idx_resuCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRdsCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCRCio_id ON deployments(portfolio_id);

-- Insert default design systems
INSERT INTO design_systems (name, description, tokens, is_public)
VALUES 
  ('Udayani Modern', 'Clean, modern design system inspired by tech industry', 
   '{"colors": {"primary": "#2563eb", "secondary": "#ec4899"}, "typography": {"fontFamily": "Inter", "fontSize": 16}}'::jsonb, true),
  ('Minimal Dark', 'Minimalist dark theme for professionals', 
   '{"colors": {"primary": "#ffffff", "secondary": "#9ca3af"}, "typography": {"fontFamily": "Mono", "fontSize": 14}}'::jsonb, true),
  ('Tech Forward', 'Bold, tech-focused design system', 
   '{"colors": {"primary": "#06b6d4", "secondary": "#0f766e"}, "typography": {"fontFamily": "Jetbrains Mono", "fontSize": 15}}'::jsonb, true)
ON CONFLICT DO NOTHING;
