"""Track processed content, including missing deadlines; preserve deleted identities."""

from dataclasses import dataclass
from datetime import date
from collections.abc import Iterable
import re

import psycopg

from scraper.db.connection import DatabaseError, read_rows, run_database_operation
from scraper.identity import canonical_source_url

HISTORY_BATCH_SIZE = 500

class HistoryError(DatabaseError):
    """A history lookup failed; processing must not continue without it."""


@dataclass(frozen=True)
class ArticleHistory:
    hash: str | None
    deleted: bool
    upload_date: date
    source_index_id: int | None = None


def record_missing_deadline(connection, source_url: str, title: str, content_hash: str,
                            upload_date: date, source_index_id: int) -> bool:
    """Remember processed content without writing an opportunity or clearing deletion."""
    if (not isinstance(content_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', content_hash)
            or type(upload_date) is not date or type(source_index_id) is not int or source_index_id <= 0):
        raise HistoryError('Invalid missing-deadline history metadata.')
    source_url = canonical_source_url(source_url)

    def persist(active):
        with active.transaction():
            row = active.execute('''
                INSERT INTO public.article_history (source_url, title, hash, upload_date, source_index_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_url) DO UPDATE SET
                    title = EXCLUDED.title,
                    hash = EXCLUDED.hash,
                    source_index_id = COALESCE(article_history.source_index_id, EXCLUDED.source_index_id)
                WHERE NOT article_history.deleted
                RETURNING source_url
            ''', (source_url, title, content_hash, upload_date, source_index_id)).fetchone()
            return row is not None

    try:
        return run_database_operation(connection, persist)
    except psycopg.Error as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise HistoryError(f'Missing-deadline history write failed{state}.') from None


def check_history_table(connection: psycopg.Connection) -> None:
    try:
        read_rows(connection, 'SELECT source_url, title, hash, deleted, upload_date, source_index_id FROM public.article_history LIMIT 0')
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
            rows = read_rows(connection, '''
                SELECT source_url, hash, deleted, upload_date, source_index_id FROM public.article_history
                WHERE source_url = ANY(%s)
            ''', (keys[start:start + HISTORY_BATCH_SIZE],))
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
