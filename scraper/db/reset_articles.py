"""Explicit, interactive article reset using a pasted database URL."""

import argparse
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict

from scraper.config import SQL_DIR


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        database_url = input('Paste database URL: ').strip()
        if not database_url.startswith(('postgresql://', 'postgres://')):
            print('Reset cancelled: enter a PostgreSQL connection URL.', file=sys.stderr)
            return 1
        try:
            target = conninfo_to_dict(database_url)
        except (psycopg.Error, ValueError):
            print('Reset cancelled: invalid PostgreSQL connection URL.', file=sys.stderr)
            return 1
        if not target.get('host') or not target.get('dbname'):
            print('Reset cancelled: URL must specify a host and database.', file=sys.stderr)
            return 1

        # repr escapes terminal control characters in user-supplied target names.
        print(f"Target host: {target['host']!r}; database: {target['dbname']!r}")
        print('This permanently clears opportunities, article history, and deletion markers. '
              'Website indexes are preserved. Stop collection before continuing.')
        if input('Type RESET to continue: ') != 'RESET':
            print('Reset cancelled.')
            return 1

        reset_sql = (SQL_DIR / 'reset_articles.sql').read_text(encoding='utf-8')
        # The SQL file owns BEGIN/COMMIT. Closing on failure rolls back its transaction.
        with psycopg.connect(database_url, connect_timeout=10, autocommit=True) as connection:
            connection.execute(reset_sql)
    except (EOFError, KeyboardInterrupt):
        print('\nReset cancelled.', file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print('Reset failed: could not read sql/reset_articles.sql.', file=sys.stderr)
        return 1
    except psycopg.Error:
        print('Reset failed: PostgreSQL connection or SQL error.', file=sys.stderr)
        return 1

    print('Reset complete: opportunities and article history cleared where present; '
          'website indexes preserved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
