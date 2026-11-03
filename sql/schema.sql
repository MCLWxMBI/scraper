-- Shared scraper database schema. The caller owns the transaction.
-- Index schema: website/drizzle/0002_large_edwin_jarvis.sql.
-- Opportunity fields and persistence requirements:
-- https://github.com/MCLWxMBI/website/blob/main/docs/contracts.md#opportunity
-- https://github.com/MCLWxMBI/website/blob/main/docs/future-plans.md#opportunity-persistence
-- CHECK constraints cannot contain subqueries. Keep array validation in a pure
-- function so null/blank items, empty arrays and duplicate labels are rejected.
-- Repeated full-text paragraphs are allowed; category/tag labels are unique.
CREATE OR REPLACE FUNCTION public.opportunity_text_array_valid(
    items TEXT[], unique_labels BOOLEAN DEFAULT FALSE
) RETURNS BOOLEAN
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $$
    SELECT COALESCE(
        array_ndims(items) = 1
        AND cardinality(items) > 0
        AND NOT EXISTS (
            SELECT 1 FROM unnest(items) AS item
            WHERE item IS NULL OR item !~ '[^[:space:]]'
               OR item ~ '^[[:space:]]|[[:space:]]$'
        )
        AND (NOT unique_labels OR cardinality(items) = (
            SELECT count(DISTINCT lower(item)) FROM unnest(items) AS item
        )), FALSE
    );
$$;

CREATE TABLE IF NOT EXISTS public.website_indexes (
    id BIGSERIAL PRIMARY KEY NOT NULL,
    name VARCHAR(255) NOT NULL,
    index_url TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    CONSTRAINT website_indexes_tags_valid CHECK (
        cardinality(tags) = 0 OR public.opportunity_text_array_valid(tags, TRUE)
    )
);

CREATE TABLE IF NOT EXISTS public.opportunities (
    id TEXT PRIMARY KEY CHECK (id ~ '[^[:space:]]'),
    title TEXT NOT NULL CHECK (title ~ '[^[:space:]]'),
    full_text TEXT[] NOT NULL
        CHECK (public.opportunity_text_array_valid(full_text)),
    source_url TEXT NOT NULL UNIQUE CHECK (source_url ~ '^https://[^[:space:]]+$'),
    website_id BIGINT NOT NULL REFERENCES public.website_indexes(id) ON DELETE RESTRICT,
    source_org TEXT NOT NULL CHECK (source_org ~ '[^[:space:]]'),
    jurisdiction TEXT NOT NULL CHECK (jurisdiction IN ('Commonwealth', 'Victoria')),
    start_date TIMESTAMPTZ NULL,
    submission_deadline TIMESTAMPTZ NOT NULL
        CHECK (isfinite(submission_deadline)),
    submission_deadline_precision TEXT DEFAULT 'datetime' NOT NULL,
    CONSTRAINT opportunities_deadline_precision_valid CHECK (
        submission_deadline_precision IN ('datetime', 'month')
    ),
    CONSTRAINT opportunities_deadline_month_normalized CHECK (
        submission_deadline_precision <> 'month' OR (
            submission_deadline AT TIME ZONE 'UTC' = date_trunc('month', submission_deadline AT TIME ZONE 'UTC')
            AND EXTRACT(YEAR FROM submission_deadline AT TIME ZONE 'UTC') BETWEEN 1 AND 9999
        )
    ),
    category TEXT[] NOT NULL CHECK (
        public.opportunity_text_array_valid(category, TRUE)
        AND category <@ ARRAY[
            'Biodiversity & ecosystems',
            'Climate change',
            'First Nations & cultural heritage',
            'Water & resources',
            'Communities & environment'
        ]::TEXT[]
    ),
    tags TEXT[] NULL CHECK (
        tags IS NULL OR public.opportunity_text_array_valid(tags, TRUE)
    ),
    summary TEXT NULL CHECK (summary IS NULL OR summary ~ '[^[:space:]]'),
    location JSONB NULL CHECK (
        location IS NULL OR (
            jsonb_typeof(location) = 'object'
            AND jsonb_typeof(location -> 'label') = 'string'
            AND (location ->> 'label') ~ '[^[:space:]]'
            AND jsonb_typeof(location -> 'geometry') = 'object'
            AND location -> 'geometry' ->> 'type' IN ('Point', 'Polygon', 'MultiPolygon')
            AND jsonb_typeof(location -> 'geometry' -> 'coordinates') = 'array'
        ) IS TRUE
    ),
    CONSTRAINT opportunities_date_order CHECK (
        start_date IS NULL OR (isfinite(start_date) AND start_date <= submission_deadline)
    )
);

-- upload_date is the Sydney calendar date captured before the first successfully
-- saved structuring attempt. Direct/trigger inserts use the Sydney date default.
-- source_index_id is the original website_indexes ID, not a hostname-derived ID.
-- Content history survives physical opportunity deletion. URL is the identity;
-- hash is the last successfully saved normalized extraction, never a title hash.
-- NULL hashes are reserved for untracked direct inserts/deletion markers.
CREATE TABLE IF NOT EXISTS public.article_history (
    source_url TEXT PRIMARY KEY CHECK (source_url ~ '^https://[^[:space:]]+$'),
    title TEXT NOT NULL CHECK (title ~ '[^[:space:]]'),
    hash TEXT NULL CHECK (hash IS NULL OR hash ~ '^[0-9a-f]{64}$'),
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    upload_date DATE NOT NULL DEFAULT ((clock_timestamp() AT TIME ZONE 'Australia/Sydney')::date),
    source_index_id BIGINT REFERENCES public.website_indexes(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS opportunities_website_id_idx
    ON public.opportunities (website_id);
CREATE INDEX IF NOT EXISTS article_history_source_recent_idx
    ON public.article_history (source_index_id, upload_date DESC NULLS LAST, source_url);

-- Website application tables; the scraper does not read or write these.
DO $$ BEGIN
    CREATE TYPE public.user_role AS ENUM ('user', 'admin');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role public.user_role NOT NULL DEFAULT 'user',
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.static_pages (
    slug TEXT PRIMARY KEY,
    content_html TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by INTEGER REFERENCES public.users(id) ON DELETE SET NULL
);

-- Lock the persistent identity even when a direct insert has no history yet.
-- Scraper writes already hold this lock when committing their successful hash.
-- A deleted marker is never cleared by an opportunity insert/update.
CREATE OR REPLACE FUNCTION public.guard_deleted_opportunity()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    was_deleted BOOLEAN;
BEGIN
    INSERT INTO public.article_history (source_url, title)
    VALUES (NEW.source_url, NEW.title)
    ON CONFLICT (source_url) DO NOTHING;

    SELECT deleted INTO was_deleted FROM public.article_history
    WHERE source_url = NEW.source_url FOR UPDATE;
    IF was_deleted THEN
        RAISE EXCEPTION 'A deleted article cannot be recreated'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.remember_deleted_opportunity()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.article_history (source_url, title, hash, deleted)
    VALUES (OLD.source_url, OLD.title, NULL, TRUE)
    ON CONFLICT (source_url) DO UPDATE SET
        title = EXCLUDED.title,
        deleted = TRUE;
    -- Preserve the successful hash, upload_date and source_index_id; retain history.
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS opportunities_guard_deleted ON public.opportunities;
CREATE TRIGGER opportunities_guard_deleted
BEFORE INSERT OR UPDATE ON public.opportunities
FOR EACH ROW EXECUTE FUNCTION public.guard_deleted_opportunity();

DROP TRIGGER IF EXISTS opportunities_remember_deleted ON public.opportunities;
CREATE TRIGGER opportunities_remember_deleted
AFTER DELETE ON public.opportunities
FOR EACH ROW EXECUTE FUNCTION public.remember_deleted_opportunity();

-- Delete a post using DELETE FROM public.opportunities WHERE id = ... .
-- The row is physically removed; the trigger atomically retains deleted=TRUE.
-- Discovery skips that canonical source URL before extraction, even if it changes.
-- To deliberately reimport, first ensure the opportunity is gone, then explicitly
-- DELETE its article_history row. Never cascade opportunity deletion into history.
-- All opportunity writers must store canonical source_url values, as the scraper
-- does. TRUNCATE bypasses row deletion triggers: reserve it for disposable resets.

-- Snake-case columns map to the contract's camelCase fields at the API boundary.
-- Serialize timestamps as ISO 8601 UTC ending in Z. SQL NULL tags/start_date
-- remain JSON null; omit summary/location when NULL. Do not persist status:
-- the frontend derives open/upcoming/closed from start_date and deadline.
-- Validate full HTTPS URLs, plain text, canonical Invite-only spelling and full
-- GeoJSON coordinate bounds/ring closure in the application before inserting.
-- JSON shape checks here do not replace geometry validation.
