"""Read the category choices used for Claude classification."""

import psycopg

from scraper.db.connection import DatabaseError


def load_categories(connection: psycopg.Connection) -> tuple[str, ...]:
    try:
        rows = connection.execute('SELECT name FROM public.categories ORDER BY id').fetchall()
    except psycopg.Error:
        raise DatabaseError('Could not load categories from public.categories; check schema and SELECT permissions.') from None
    if not rows:
        raise DatabaseError('No categories configured in public.categories; run the category seed first.')
    return tuple(row[0] for row in rows)
