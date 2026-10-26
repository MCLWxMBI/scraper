"""Create the scraper schema and seed indexes; run without concurrent writers."""

from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg import sql

from scraper.config import ConfigurationError, SQL_DIR, load_environment
from scraper.db.connection import connect_database
from scraper.db.opportunities import check_opportunity_table


class SetupError(Exception):
    """A setup failure with a message safe to display without credentials."""


def check_schema(conn: psycopg.Connection) -> str:
    """Require the upstream schema and return its owned ID sequence name."""
    columns = conn.execute("""
        SELECT attname, format_type(atttypid, atttypmod), attnotnull,
               pg_get_expr(d.adbin, d.adrelid), attidentity, attgenerated
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'public.website_indexes'::regclass
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
    """).fetchall()
    sequence = conn.execute(
        "SELECT pg_get_serial_sequence('public.website_indexes', 'id')"
    ).fetchone()[0]
    if sequence is None:
        raise SetupError('Incompatible website_indexes schema: ID needs an owned sequence.')
    default = conn.execute(
        "SELECT format('nextval(%%L::regclass)', %s::regclass::text)", (sequence,)
    ).fetchone()[0]
    expected = [
        ('id', 'bigint', True, default, '', ''),
        ('name', 'character varying(255)', True, None, '', ''),
        ('index_url', 'text', True, None, '', ''),
        ('active', 'boolean', True, 'true', '', ''),
        ('notes', 'text', False, None, '', ''),
    ]
    # Column order is immaterial; all SQL uses explicit column names.
    if sorted(columns) != sorted(expected):
        raise SetupError('Incompatible website_indexes schema: columns or defaults differ.')
    primary_keys = conn.execute("""
        SELECT ARRAY(
            SELECT attname FROM unnest(c.conkey) WITH ORDINALITY AS k(num, pos)
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.num
            ORDER BY k.pos
        )
        FROM pg_constraint c
        WHERE c.conrelid = 'public.website_indexes'::regclass AND c.contype = 'p'
    """).fetchall()
    if primary_keys != [(['id'],)]:
        raise SetupError('Incompatible website_indexes schema: ID must be the primary key.')
    sequence_settings = conn.execute("""
        SELECT seqtypid::regtype::text, seqincrement, seqcycle
        FROM pg_sequence WHERE seqrelid = %s::regclass
    """, (sequence,)).fetchone()
    if sequence_settings != ('bigint', 1, False):
        raise SetupError('Incompatible website_indexes schema: unexpected ID sequence settings.')
    return sequence


def check_existing_articles(conn: psycopg.Connection) -> None:
    """Refuse an initial history upgrade over untracked opportunity data."""
    opportunities, history = conn.execute(
        "SELECT to_regclass('public.opportunities'), to_regclass('public.article_history')"
    ).fetchone()
    if opportunities is None:
        return
    if history is None:
        untracked = conn.execute('SELECT EXISTS (SELECT 1 FROM public.opportunities)').fetchone()[0]
    else:
        untracked = conn.execute("""
            SELECT EXISTS (
                SELECT 1 FROM public.opportunities o
                LEFT JOIN public.article_history h ON h.source_url = o.source_url
                WHERE h.source_url IS NULL OR h.hash IS NULL OR h.deleted
            )
        """).fetchone()[0]
    if untracked:
        raise SetupError(
            'Existing opportunities lack successful article history. '
            'For a disposable database, manually run sql/reset_articles.sql before setup. '
            'No existing articles were deleted.'
        )


def check_history_schema(conn: psycopg.Connection) -> None:
    columns = conn.execute("""
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid)
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'public.article_history'::regclass
          AND a.attnum > 0 AND NOT a.attisdropped
    """).fetchall()
    # Compare the date default semantically across PostgreSQL deparser formatting.
    normalized = []
    for name, kind, required, default in columns:
        if name == 'upload_date' and default is not None:
            default = default.replace('::text', '').replace('(', '').replace(')', '').replace(' ', '')
        normalized.append((name, kind, required, default))
    expected = [('source_url', 'text', True, None), ('title', 'text', True, None),
                ('hash', 'text', False, None), ('deleted', 'boolean', True, 'false'),
                ('upload_date', 'date', True, "clock_timestampATTIMEZONE'Australia/Sydney'::date"),
                ('source_index_id', 'bigint', False, None)]
    if sorted(normalized) != sorted(expected):
        raise SetupError('Incompatible article_history schema: columns or defaults differ.')
    primary = conn.execute("""
        SELECT ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(num, pos)
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.num ORDER BY k.pos)
        FROM pg_constraint c
        WHERE c.conrelid = 'public.article_history'::regclass AND c.contype = 'p'
    """).fetchall()
    if primary != [(['source_url'],)]:
        raise SetupError('Incompatible article_history schema: source_url must be the primary key.')


def seed_database(conn: psycopg.Connection) -> int:
    """Apply setup inside the caller's transaction and return extra row count."""
    check_existing_articles(conn)
    conn.execute((SQL_DIR / 'schema.sql').read_text(encoding='utf-8'))
    check_history_schema(conn)
    check_opportunity_table(conn)
    sequence = check_schema(conn)
    expected = conn.execute(
        (SQL_DIR / 'seed_website_indexes.sql').read_text(encoding='utf-8')
    ).fetchall()
    if ([row[0] for row in expected] != list(range(1, 39))
            or sum(row[3] for row in expected) != 36):
        raise SetupError('The local seed must contain IDs 1–38, with 36 active rows.')
    actual = conn.execute("""
        SELECT id, name, index_url, active, notes FROM public.website_indexes
        WHERE id = ANY(%s) ORDER BY id
    """, ([row[0] for row in expected],)).fetchall()
    if actual != expected:
        raise SetupError('Seed verification failed: stored rows differ from the local seed.')
    total, maximum = conn.execute(
        'SELECT count(*), max(id) FROM public.website_indexes'
    ).fetchone()
    namespace, name = conn.execute("""
        SELECT n.nspname, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.oid = %s::regclass
    """, (sequence,)).fetchone()
    last_value = conn.execute(
        sql.SQL('SELECT last_value FROM {}').format(sql.Identifier(namespace, name))
    ).fetchone()[0]
    if last_value <= maximum:
        # setval is not transactional. Do this only after row verification, and
        # never move a sequence backward (including one advanced by deleted rows).
        conn.execute('SELECT setval(%s::regclass, %s, true)', (sequence, maximum))
    return total - len(expected)


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        load_environment()
        with connect_database() as conn:
            extra = seed_database(conn)
    except (SetupError, ConfigurationError) as exc:
        print(f'Database setup failed: {exc}', file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        # Server/connection messages can contain connection strings or values.
        state = f' (SQLSTATE {exc.sqlstate})' if exc.sqlstate else ''
        print(f'Database setup failed: PostgreSQL connection or SQL error{state}.', file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print('Database setup failed: could not read local configuration or SQL files.', file=sys.stderr)
        return 1
    print(f'Seeded 38 website indexes: 36 active, 2 inactive; preserved {extra} additional rows.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
