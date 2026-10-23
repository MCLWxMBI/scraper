"""Read successful content versions; deleted identities always remain excluded."""

from dataclasses import dataclass
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


def check_history_table(connection: psycopg.Connection) -> None:
    try:
        connection.execute('SELECT source_url, title, hash, deleted FROM public.article_history LIMIT 0')
    except psycopg.Error:
        raise HistoryError('Article history is unavailable; run manual schema setup.') from None


def load_history(connection: psycopg.Connection, urls: Iterable[str]) -> dict[str, ArticleHistory]:
    keys = list(dict.fromkeys(urls))
    history = {}
    try:
        for start in range(0, len(keys), HISTORY_BATCH_SIZE):
            rows = connection.execute('''
                SELECT source_url, hash, deleted FROM public.article_history
                WHERE source_url = ANY(%s)
            ''', (keys[start:start + HISTORY_BATCH_SIZE],)).fetchall()
            history.update((url, ArticleHistory(digest, deleted)) for url, digest, deleted in rows)
    except psycopg.Error:
        raise HistoryError('Article history lookup failed; stopping before Claude processing.') from None
    return history
