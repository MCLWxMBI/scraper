"""Explicit DATABASE_URL connections with sanitized errors."""

import os
import sys
import time
import psycopg

from scraper.config import ConfigurationError


class DatabaseError(ConfigurationError):
    """A configuration or SQL error with safe terminal diagnostics."""


def connect_database(*, autocommit: bool = False) -> psycopg.Connection:
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        raise DatabaseError('Set DATABASE_URL in .env or the environment.')
    for attempt in range(3):
        try:
            return psycopg.connect(database_url, connect_timeout=10, autocommit=autocommit)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            if attempt == 2:
                break
            delay = 2 ** attempt
            print(f'Database connection failed; retrying in {delay}s ({attempt + 1}/2).',
                  file=sys.stderr, flush=True)
            time.sleep(delay)
        except psycopg.Error:
            break
    raise DatabaseError('Could not connect using DATABASE_URL; check configuration and database availability.') from None


