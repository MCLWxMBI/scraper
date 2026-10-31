#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$script_dir/.."

# Target only the disposable PostgreSQL service in .devcontainer/compose.yaml.
# Deliberately ignore DATABASE_URL, which may point to another environment.
exec uv run python - <<'PY'
import sys

import psycopg

try:
    with psycopg.connect(
        host='postgres', port=5432, dbname='scraper',
        user='scraper', password='scraper', connect_timeout=10,
    ) as connection:
        connection.execute('TRUNCATE TABLE public.article_history')
except psycopg.Error:
    print('History reset failed. Run inside the devcontainer with its PostgreSQL service available.',
          file=sys.stderr)
    sys.exit(1)

print('Reset devcontainer scraper.article_history, including deletion markers. '
      'Opportunities and website indexes were preserved.')
PY
