"""Map validated opportunities to PostgreSQL and persist them transactionally."""

from datetime import date, datetime
import re

import psycopg
from psycopg.types.json import Jsonb

from scraper.models import Opportunity
from scraper.identity import canonical_source_url
from scraper.db.connection import DatabaseError


class OpportunityStorageError(RuntimeError):
    """A storage failure whose message is safe for terminal diagnostics."""


class ArticleDeletedError(OpportunityStorageError):
    """A late save was rejected because the article was deleted."""


def opportunity_parameters(opportunity: Opportunity) -> dict:
    """Map the validated model to SQL names, native dates and JSONB parameters."""
    return {
        'id': opportunity.id,
        'title': opportunity.title,
        'full_text': opportunity.fullText,
        'source_url': canonical_source_url(opportunity.sourceUrl),
        'source_org': opportunity.sourceOrg,
        'jurisdiction': opportunity.jurisdiction,
        'start_date': (datetime.fromisoformat(opportunity.startDate)
                       if opportunity.startDate is not None else None),
        'submission_deadline': datetime.fromisoformat(opportunity.submissionDeadline),
        'submission_deadline_precision': opportunity.submissionDeadlinePrecision,
        'category': opportunity.category,
        'tags': opportunity.tags,
        'summary': opportunity.summary,
        'location': (Jsonb(opportunity.location.model_dump(mode='json'))
                     if opportunity.location is not None else None),
    }


def save_opportunity(conn: psycopg.Connection, opportunity: Opportunity, *, content_hash: str | None = None,
                     upload_date: date | None = None, source_index_id: int | None = None) -> None:
    """Atomically save a record and its input hash; never clear deleted markers.

    Reject reuse of a slug for a different source URL.

    The caller owns the connection. This commits one record when no transaction
    is already open; inside a caller transaction it uses a savepoint, leaving
    the final commit to the caller. Connection/setup configuration is separate.
    """
    if content_hash is not None and not re.fullmatch(r'[0-9a-f]{64}', content_hash):
        raise OpportunityStorageError('Invalid extracted-content hash.')
    parameters = opportunity_parameters(opportunity)
    stored_date = opportunity.upload_date if upload_date is None else upload_date
    if type(stored_date) is not date:
        raise OpportunityStorageError('Upload date must be a date-only value.')
    if source_index_id is not None and (type(source_index_id) is not int or source_index_id <= 0):
        raise OpportunityStorageError('Source index ID must be a positive website index ID.')
    parameters.update(content_hash=content_hash, upload_date=stored_date,
                      source_index_id=source_index_id,
                      location_lookup_failed=opportunity.location_lookup_failed)
    try:
        with conn.transaction():
            # This upsert acquires the same identity-row lock as the deletion
            # trigger. Never resurrect a tombstone, including after a Claude call.
            tracked = conn.execute("""
                INSERT INTO public.article_history (source_url, title, hash, upload_date, source_index_id)
                VALUES (%(source_url)s, %(title)s, %(content_hash)s, %(upload_date)s, %(source_index_id)s)
                ON CONFLICT (source_url) DO UPDATE SET
                    title = EXCLUDED.title,
                    hash = COALESCE(EXCLUDED.hash, article_history.hash),
                    source_index_id = COALESCE(article_history.source_index_id, EXCLUDED.source_index_id)
                WHERE NOT article_history.deleted
                RETURNING source_url
            """, parameters).fetchone()
            if tracked is None:
                raise ArticleDeletedError('Article was deleted; refusing to recreate its opportunity.')
            saved = conn.execute("""
                INSERT INTO public.opportunities (
                    id, title, full_text, source_url, source_org, jurisdiction,
                    start_date, submission_deadline, submission_deadline_precision, category, tags, summary, location
                ) VALUES (
                    %(id)s, %(title)s, %(full_text)s, %(source_url)s, %(source_org)s,
                    %(jurisdiction)s, %(start_date)s, %(submission_deadline)s,
                    %(submission_deadline_precision)s,
                    %(category)s, %(tags)s, %(summary)s, %(location)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    full_text = EXCLUDED.full_text,
                    source_org = EXCLUDED.source_org,
                    jurisdiction = EXCLUDED.jurisdiction,
                    start_date = EXCLUDED.start_date,
                    submission_deadline = EXCLUDED.submission_deadline,
                    submission_deadline_precision = EXCLUDED.submission_deadline_precision,
                    category = EXCLUDED.category,
                    tags = EXCLUDED.tags,
                    summary = EXCLUDED.summary,
                    location = CASE WHEN %(location_lookup_failed)s THEN opportunities.location ELSE EXCLUDED.location END
                WHERE opportunities.source_url = EXCLUDED.source_url
                RETURNING id
            """, parameters).fetchone()
            if saved is None:
                raise OpportunityStorageError(
                    f'Slug collision for {opportunity.id!r}: stored source URL differs.'
                )
    except psycopg.Error as exc:
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        raise OpportunityStorageError(f'Opportunity database write failed{state}.') from None


def check_opportunity_table(connection: psycopg.Connection) -> None:
    try:
        connection.execute('''
            SELECT id, title, full_text, source_url, source_org, jurisdiction,
                   start_date, submission_deadline, submission_deadline_precision, category, tags, summary, location
            FROM public.opportunities LIMIT 0
        ''')
    except psycopg.Error:
        raise DatabaseError('Opportunity table is unavailable; check the current sql/schema.sql, development database setup and permissions.') from None
