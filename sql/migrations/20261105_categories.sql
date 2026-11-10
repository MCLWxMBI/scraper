-- Caller owns the transaction. Apply schema.sql first to create categories.
ALTER TABLE public.opportunities DROP COLUMN IF EXISTS tags;
ALTER TABLE public.opportunities DROP CONSTRAINT IF EXISTS opportunities_category_check;
ALTER TABLE public.opportunities DROP CONSTRAINT IF EXISTS opportunities_category_valid;
ALTER TABLE public.opportunities ADD CONSTRAINT opportunities_category_valid
    CHECK (public.opportunity_text_array_valid(category, TRUE));
