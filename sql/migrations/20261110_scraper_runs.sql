-- Explicit deployment prerequisite; the workflow never creates tables.
CREATE TABLE IF NOT EXISTS public.scraper_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    extracted_opportunities JSONB NOT NULL DEFAULT '[]'::jsonb
);
