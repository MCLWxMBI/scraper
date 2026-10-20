"""Shared DATABASE_URL configuration and active index selection."""

import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg


PROJECT_DIR = Path(__file__).resolve().parent


class DatabaseError(RuntimeError):
    """A configuration or SQL error with safe terminal diagnostics."""


def load_environment() -> None:
    try:
        load_dotenv(PROJECT_DIR / '.env', override=False)
    except (OSError, UnicodeError):
        raise DatabaseError('Could not read project environment configuration.') from None


def connect_database(*, autocommit: bool = False) -> psycopg.Connection:
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        raise DatabaseError('Set DATABASE_URL in .env or the environment.')
    try:
        return psycopg.connect(database_url, connect_timeout=10, autocommit=autocommit)
    except psycopg.Error:
        raise DatabaseError('Could not connect using DATABASE_URL; check configuration and database availability.') from None


def load_active_indexes(connection: psycopg.Connection) -> list[tuple[str, str]]:
    try:
        return connection.execute('''
            SELECT name, index_url FROM public.website_indexes
            WHERE active = TRUE ORDER BY lower(name), id
        ''').fetchall()
    except psycopg.Error:
        raise DatabaseError('Could not load active website indexes; check schema setup and permissions.') from None


def check_opportunity_table(connection: psycopg.Connection) -> None:
    try:
        connection.execute('''
            SELECT id, title, full_text, source_url, source_org, jurisdiction,
                   start_date, submission_deadline, category, tags, summary, location
            FROM public.opportunities LIMIT 0
        ''')
    except psycopg.Error:
        raise DatabaseError('Opportunity table is unavailable; check schema setup and permissions.') from None
