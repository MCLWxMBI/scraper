"""Read successful content versions; deleted identities always remain excluded."""

from dataclasses import dataclass
from datetime import date
from collections.abc import Iterable

import psycopg

from scraper.db.connection import DatabaseError

HISTORY_BATCH_SIZE = 500

class HistoryError(DatabaseError):
    """A history lookup failed; processing must not continue without it."""


@dataclass(frozen=True)
class ArticleHistory:
    hash: str | None
    deleted: bool
    upload_date: date
    source_index_id: int | None = None


def check_history_table(connection: psycopg.Connection) -> None:
    try:
        connection.execute('SELECT source_url, title, hash, deleted, upload_date, source_index_id FROM public.article_history LIMIT 0')
    except psycopg.errors.UndefinedTable as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: public.article_history is missing; check schema setup{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.UndefinedColumn as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: a required article_history column is missing; check schema setup{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.InsufficientPrivilege as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: permission denied; check SELECT access to public.article_history{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.QueryCanceled as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: query cancelled or statement timeout exceeded{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.InFailedSqlTransaction as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: database transaction is aborted after an earlier SQL error{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.InterfaceError as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: database connection is closed or unusable{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.OperationalError as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: database connection or operational failure; check database availability and connection timeouts{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.Error as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: unexpected database error{state}; '
            'stopping before Claude processing.'
        ) from None


def load_history(connection: psycopg.Connection, urls: Iterable[str]) -> dict[str, ArticleHistory]:
    keys = list(dict.fromkeys(urls))
    history = {}
    try:
        for start in range(0, len(keys), HISTORY_BATCH_SIZE):
            rows = connection.execute('''
                SELECT source_url, hash, deleted, upload_date, source_index_id FROM public.article_history
                WHERE source_url = ANY(%s)
            ''', (keys[start:start + HISTORY_BATCH_SIZE],)).fetchall()
            history.update((url, ArticleHistory(digest, deleted, upload_date, index_id))
                           for url, digest, deleted, upload_date, index_id in rows)
    except psycopg.errors.UndefinedTable as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: public.article_history is missing; check schema setup{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.UndefinedColumn as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: a required article_history column is missing; check schema setup{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.InsufficientPrivilege as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: permission denied; check SELECT access to public.article_history{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.QueryCanceled as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: query cancelled or statement timeout exceeded{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.errors.InFailedSqlTransaction as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: database transaction is aborted after an earlier SQL error{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.InterfaceError as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: database connection is closed or unusable{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.OperationalError as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: database connection or operational failure; check database availability and connection timeouts{state}; '
            'stopping before Claude processing.'
        ) from None
    except psycopg.Error as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(
            f'Article history lookup failed: unexpected database error{state}; '
            'stopping before Claude processing.'
        ) from None
    return history
