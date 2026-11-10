-- Align an existing run-log table with the final six-column website schema.
ALTER TABLE public.scraper_runs
    DROP CONSTRAINT IF EXISTS scraper_runs_github_run_unique,
    DROP CONSTRAINT IF EXISTS scraper_runs_status_check,
    DROP COLUMN IF EXISTS github_repository,
    DROP COLUMN IF EXISTS github_run_id,
    DROP COLUMN IF EXISTS github_run_attempt;
