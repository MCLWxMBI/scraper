"""Explicit DATABASE_URL connections with sanitized errors."""

import os
import sys
import time
import psycopg

from scraper.config import ConfigurationError


class DatabaseError(ConfigurationError):
    """A configuration or SQL error with safe terminal diagnostics."""


def is_connection_error(exc: psycopg.Error) -> bool:
    state = exc.sqlstate
    if state:
        return state.startswith('08') or state in ('57P01', '57P02', '57P03')
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


class DatabaseConnection:
    """Keep one shared handle while replacing lost underlying connections."""

    def __init__(self, connection, database_url: str, autocommit: bool):
        self._connection = connection
        self._database_url = database_url
        self._autocommit = autocommit

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *args):
        return self._connection.__exit__(*args)

    def run(self, operation):
        # A caller-owned outer transaction cannot be reconstructed safely.
        outer_transaction = self._connection.info.transaction_status in (
            psycopg.pq.TransactionStatus.INTRANS, psycopg.pq.TransactionStatus.INERROR)
        reconnect = False
        for attempt in range(3):
            try:
                if reconnect:
                    self._connection = psycopg.connect(
                        self._database_url, connect_timeout=10, autocommit=self._autocommit)
                    reconnect = False
                return operation(self._connection)
            except psycopg.Error as exc:
                if not is_connection_error(exc) or outer_transaction or attempt == 2:
                    raise
                delay = 2 ** attempt
                print(f'Database connection lost; reconnecting in {delay}s ({attempt + 1}/2).',
                      file=sys.stderr, flush=True)
                try:
                    self._connection.close()
                except psycopg.Error:
                    pass
                reconnect = True
                time.sleep(delay)


def run_database_operation(connection, operation):
    """Retry an entire read or repeatable transaction, including commit."""
    if isinstance(connection, DatabaseConnection):
        return connection.run(operation)
    return operation(connection)


def read_rows(connection, query, parameters=None):
    def read(active):
        if isinstance(connection, DatabaseConnection):
            with active.transaction():
                return active.execute(query, parameters).fetchall()
        return active.execute(query, parameters).fetchall()
    return run_database_operation(connection, read)


def connect_database(*, autocommit: bool = False) -> DatabaseConnection:
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        raise DatabaseError('Set DATABASE_URL in .env or the environment.')
    for attempt in range(3):
        try:
            connection = psycopg.connect(database_url, connect_timeout=10, autocommit=autocommit)
            return DatabaseConnection(connection, database_url, autocommit)
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


