-- Shared scraper database schema. The caller owns the transaction.
-- Index schema: website/drizzle/0002_large_edwin_jarvis.sql.
-- Opportunity fields and persistence requirements:
-- https://github.com/MCLWxMBI/website/blob/main/docs/contracts.md#opportunity
-- https://github.com/MCLWxMBI/website/blob/main/docs/future-plans.md#opportunity-persistence
CREATE TABLE IF NOT EXISTS public.website_indexes (
    id BIGSERIAL PRIMARY KEY NOT NULL,
    name VARCHAR(255) NOT NULL,
    index_url TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT
);

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

CREATE TABLE IF NOT EXISTS public.opportunities (
    id TEXT PRIMARY KEY CHECK (id ~ '[^[:space:]]'),
    title TEXT NOT NULL CHECK (title ~ '[^[:space:]]'),
    full_text TEXT[] NOT NULL
        CHECK (public.opportunity_text_array_valid(full_text)),
    source_url TEXT NOT NULL CHECK (source_url ~ '^https://[^[:space:]]+$'),
    source_org TEXT NOT NULL CHECK (source_org ~ '[^[:space:]]'),
    jurisdiction TEXT NOT NULL CHECK (jurisdiction IN ('Commonwealth', 'Victoria')),
    start_date TIMESTAMPTZ NULL,
    submission_deadline TIMESTAMPTZ NOT NULL
        CHECK (isfinite(submission_deadline)),
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

-- Snake-case columns map to the contract's camelCase fields at the API boundary.
-- Serialize timestamps as ISO 8601 UTC ending in Z. SQL NULL tags/start_date
-- remain JSON null; omit summary/location when NULL. Do not persist status:
-- the frontend derives open/upcoming/closed from start_date and deadline.
-- Validate full HTTPS URLs, plain text, canonical Invite-only spelling and full
-- GeoJSON coordinate bounds/ring closure in the application before inserting.
-- JSON shape checks here do not replace geometry validation.
