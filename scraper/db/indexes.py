"""Read active collection indexes from PostgreSQL."""

import psycopg
from scraper.db.connection import DatabaseError
from scraper.models import WebsiteIndex


def load_active_indexes(connection: psycopg.Connection) -> list[WebsiteIndex]:
    try:
        rows = connection.execute('''
            SELECT id, name, index_url FROM public.website_indexes
            WHERE active = TRUE ORDER BY lower(name), id
        ''').fetchall()
        return [WebsiteIndex(*row) for row in rows]
    except psycopg.Error:
        raise DatabaseError('Could not load active website indexes; check schema setup and permissions.') from None


