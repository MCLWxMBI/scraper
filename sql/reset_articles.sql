-- DESTRUCTIVE: explicitly invoked reset for the deliberately selected database.
-- Removes articles and deletion markers so every URL can be imported again.
-- website_indexes and its seed/sequence are left untouched. Not run by setup.
BEGIN;
DO $$
BEGIN
    IF to_regclass('public.opportunities') IS NOT NULL THEN
        TRUNCATE TABLE public.opportunities;
    END IF;
    IF to_regclass('public.article_history') IS NOT NULL THEN
        TRUNCATE TABLE public.article_history;
    END IF;
END;
$$;
COMMIT;
