"""Explicit DATABASE_URL connections with sanitized errors."""

import os
import psycopg

from scraper.config import ConfigurationError


class DatabaseError(ConfigurationError):
    """A configuration or SQL error with safe terminal diagnostics."""


def connect_database(*, autocommit: bool = False) -> psycopg.Connection:
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        raise DatabaseError('Set DATABASE_URL in .env or the environment.')
    try:
        return psycopg.connect(database_url, connect_timeout=10, autocommit=autocommit)
    except psycopg.Error:
        raise DatabaseError('Could not connect using DATABASE_URL; check configuration and database availability.') from None


