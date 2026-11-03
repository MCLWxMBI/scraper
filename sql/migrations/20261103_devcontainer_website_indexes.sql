-- Local devcontainer upgrade from the previous scraper schema.
-- Caller owns the transaction. Refuse ambiguous data rather than delete it.
ALTER TABLE public.website_indexes ADD COLUMN tags TEXT[] NOT NULL DEFAULT '{}'::TEXT[];
ALTER TABLE public.website_indexes ADD CONSTRAINT website_indexes_tags_valid
    CHECK (cardinality(tags) = 0 OR public.opportunity_text_array_valid(tags, TRUE));

ALTER TABLE public.opportunities ADD COLUMN website_id BIGINT;
UPDATE public.opportunities o SET website_id = h.source_index_id
FROM public.article_history h WHERE h.source_url = o.source_url;
-- NOT NULL / FK validation aborts the entire upgrade for unmapped identities.
ALTER TABLE public.opportunities ALTER COLUMN website_id SET NOT NULL;
ALTER TABLE public.opportunities ADD CONSTRAINT opportunities_website_id_fkey
    FOREIGN KEY (website_id) REFERENCES public.website_indexes(id) ON DELETE RESTRICT;
ALTER TABLE public.opportunities ADD CONSTRAINT opportunities_source_url_unique UNIQUE (source_url);
ALTER TABLE public.opportunities DROP CONSTRAINT opportunities_date_order;
ALTER TABLE public.opportunities ADD CONSTRAINT opportunities_date_order
    CHECK (start_date IS NULL OR (isfinite(start_date) AND start_date <= submission_deadline));

ALTER TABLE public.article_history DROP CONSTRAINT article_history_source_index_id_fkey;
ALTER TABLE public.article_history ADD CONSTRAINT article_history_source_index_id_fkey
    FOREIGN KEY (source_index_id) REFERENCES public.website_indexes(id) ON DELETE SET NULL;
