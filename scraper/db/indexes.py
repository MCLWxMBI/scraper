"""Read active collection indexes from PostgreSQL."""

import psycopg
from scraper.db.connection import DatabaseError


def load_active_indexes(connection: psycopg.Connection) -> list[tuple[str, str]]:
    try:
        return connection.execute('''
            SELECT name, index_url FROM public.website_indexes
            WHERE active = TRUE ORDER BY lower(name), id
        ''').fetchall()
    except psycopg.Error:
        raise DatabaseError('Could not load active website indexes; check schema setup and permissions.') from None


