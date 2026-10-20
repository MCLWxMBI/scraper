"""Map validated opportunities to PostgreSQL and persist them transactionally."""

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from scraper.models import Opportunity
from scraper.db.connection import DatabaseError


class OpportunityStorageError(RuntimeError):
    """A storage failure whose message is safe for terminal diagnostics."""


def opportunity_parameters(opportunity: Opportunity) -> dict:
    """Map the validated model to SQL names, native dates and JSONB parameters."""
    return {
        'id': opportunity.id,
        'title': opportunity.title,
        'full_text': opportunity.fullText,
        'source_url': opportunity.sourceUrl,
        'source_org': opportunity.sourceOrg,
        'jurisdiction': opportunity.jurisdiction,
        'start_date': (datetime.fromisoformat(opportunity.startDate)
                       if opportunity.startDate is not None else None),
        'submission_deadline': datetime.fromisoformat(opportunity.submissionDeadline),
        'category': opportunity.category,
        'tags': opportunity.tags,
        'summary': opportunity.summary,
        'location': (Jsonb(opportunity.location.model_dump(mode='json'))
                     if opportunity.location is not None else None),
    }


def save_opportunity(conn: psycopg.Connection, opportunity: Opportunity) -> None:
    """Upsert a record, rejecting reuse of a slug for a different source URL.

    The caller owns the connection. This commits one record when no transaction
    is already open; inside a caller transaction it uses a savepoint, leaving
    the final commit to the caller. Connection/setup configuration is separate.
    """
    parameters = opportunity_parameters(opportunity)
    try:
        with conn.transaction():
            saved = conn.execute("""
                INSERT INTO public.opportunities (
                    id, title, full_text, source_url, source_org, jurisdiction,
                    start_date, submission_deadline, category, tags, summary, location
                ) VALUES (
                    %(id)s, %(title)s, %(full_text)s, %(source_url)s, %(source_org)s,
                    %(jurisdiction)s, %(start_date)s, %(submission_deadline)s,
                    %(category)s, %(tags)s, %(summary)s, %(location)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    full_text = EXCLUDED.full_text,
                    source_org = EXCLUDED.source_org,
                    jurisdiction = EXCLUDED.jurisdiction,
                    start_date = EXCLUDED.start_date,
                    submission_deadline = EXCLUDED.submission_deadline,
                    category = EXCLUDED.category,
                    tags = EXCLUDED.tags,
                    summary = EXCLUDED.summary,
                    location = EXCLUDED.location
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
                   start_date, submission_deadline, category, tags, summary, location
            FROM public.opportunities LIMIT 0
        ''')
    except psycopg.Error:
        raise DatabaseError('Opportunity table is unavailable; check schema setup and permissions.') from None
