"""Collect live or saved articles and validate them with Claude.

Run ``uv run python main.py`` or use ``--index NAME --limit 1`` for a small
development run. Use --text for JSON-array .txt output instead, or --fixtures for
saved historical HTML/PDF input and text output. Live discovery skips deleted
URLs and successful unchanged article content before Claude calls.
ANTHROPIC_API_KEY and CLAUDE_MODEL can be supplied in the project's .env file.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from anthropic import Anthropic
import psycopg
from playwright.sync_api import Browser, sync_playwright

from scraper import extraction, discovery, text_export
from scraper.config import load_environment
from scraper.decision_log import DecisionLog, DecisionLogError, DEFAULT_LOG
from scraper.fixtures import FixtureCollection
from scraper.db.connection import DatabaseError, connect_database
from scraper.db.indexes import load_active_indexes
from scraper.db.history import HistoryError, check_history_table
from scraper.db.opportunities import (
    OpportunityStorageError, check_opportunity_table, save_opportunity,
)
from scraper.structuring import (
    CLAUDE_TIMEOUT_SECONDS,
    InvalidListingError,
    article_slug,
    canonical_source_url,
    structure_listing,
)


def _error(exc: Exception) -> str:
    return f'{type(exc).__name__}: {exc}'[:600]


def compose_indexes(
    indexes: Iterable[tuple[str, str]],
    browser: Browser | None,
    output_dir: str | Path,
    limit: int | None = None,
    *,
    client: Anthropic,
    model: str,
    output_mode: Literal['db', 'txt'] = 'db',
    connection: psycopg.Connection | None = None,
    fixtures: FixtureCollection | None = None,
    decision_log: DecisionLog | None = None,
) -> int:
    """Save validated records to the selected destination and continue on errors.

    The caller owns the browser and API client; fixtures need no browser.
    Helper Source objects are passed
    unchanged to extraction. Missing deadlines are normal invalid results; API,
    traversal, extraction, database/file errors and slug collisions cause a nonzero exit.
    """
    if limit is not None and limit <= 0:
        raise ValueError('limit must be a positive integer')
    if output_mode not in {'db', 'txt'}:
        raise ValueError('output_mode must be db or txt')
    if fixtures is not None and output_mode != 'txt':
        raise ValueError('Fixture input requires text output')
    if fixtures is None and connection is None:
        raise ValueError('Live discovery requires a history database connection')
    output_dir = Path(output_dir)
    completed = failed = empty = skipped = extracted = valid = invalid = extraction_failed = 0
    source_failures = 0
    history_skipped = 0
    identities: dict[str, str] = {}

    for name, url in indexes:
        decision = decision_log.for_index(name, url) if decision_log else None
        skip_reason = fixtures.skip_reason(url) if fixtures is not None else None
        if skip_reason is not None:
            skipped += 1
            print(f'{name}: SKIPPED ({skip_reason})', flush=True)
            continue

        path = output_dir / text_export.index_filename(name, url)
        index_failed = False
        index_invalid = 0
        index_source_failures = 0
        records: list[dict] = []
        selected_hashes = {}

        def source_failed(source_url: str, reason: str, *, phase='processing', logged=False) -> None:
            nonlocal source_failures, index_source_failures
            if decision is not None and not logged:
                decision(source_url, 'failed', reason=phase, current_hash=selected_hashes.get(source_url))
            source_failures += 1
            index_source_failures += 1
            if output_mode == 'txt':
                print(f'FAIL {source_url} — {reason}', file=sys.stderr, flush=True)

        destination = str(path) if output_mode == 'txt' else 'PostgreSQL'
        action = 'reading saved articles' if fixtures is not None else 'traversing'
        print(f'{name}: {action}; output={destination}', flush=True)
        if limit is not None:
            print(f'{name}: DEVELOPMENT LIMIT: at most {limit} listings', flush=True)
        try:
            if output_mode == 'txt':
                output_dir.mkdir(parents=True, exist_ok=True)
                text_export.write_records(path, records)
            try:
                if fixtures is not None:
                    prepared = discovery.prepare_articles(
                        fixtures.sources(url), lambda source: fixtures.extract(source, url),
                        lambda urls: {}, limit=limit, decision=decision,
                    )
                else:
                    prepared = discovery.discover_articles(name, url, browser, connection, limit=limit,
                                                          **({'decision': decision} if decision else {}))
            except DecisionLogError:
                raise
            except HistoryError as exc:
                print(f'{name}: HISTORY FAILED: {_error(exc)} [index={url}]', file=sys.stderr, flush=True)
                return 1
            except Exception as exc:
                if decision is not None:
                    decision(url, 'failed', reason='traversal')
                index_failed = True
                print(f'{name}: TRAVERSAL FAILED: {_error(exc)} [index={url}]', file=sys.stderr, flush=True)
            else:
                selected = prepared.articles
                selected_hashes = {article.source.url: article.hash for article in selected}
                print(f'{name}: {prepared.discovered} listings discovered, {len(selected)} selected', flush=True)
                if len(selected) < prepared.discovered:
                    print(f'{name}: LIMITED RUN: remaining listings were intentionally not processed', flush=True)
                if not prepared.discovered:
                    empty += 1
                    print(f'{name}: EMPTY: no listings discovered', flush=True)

                for number, article in enumerate(selected, start=1):
                    source = article.source
                    if article.skipped:
                        history_skipped += 1
                        if article.skipped == 'unchanged':
                            extracted += 1
                        print(f'{name}: SKIPPED ({article.skipped}): {source.url}', flush=True)
                        continue
                    if article.error is not None:
                        if article.invalid:
                            invalid += 1
                            index_invalid += 1
                            source_failed(source.url, article.error, logged=True)
                        else:
                            extraction_failed += 1
                            index_failed = True
                            source_failed(source.url, f'extraction: {article.error}', logged=True)
                            if output_mode == 'db':
                                print(f'{name}: EXTRACTION FAILED: {source.url}: {article.error}', file=sys.stderr, flush=True)
                        continue
                    text = article.text
                    extracted += 1

                    try:
                        source_url = canonical_source_url(source.url)
                        identifier = article_slug(source_url)
                    except ValueError as exc:
                        invalid += 1
                        index_invalid += 1
                        source_failed(source.url, str(exc), phase='validation')
                        if output_mode == 'db':
                            print(f'{name}: INVALID: {source.url}: {exc}', file=sys.stderr, flush=True)
                        continue
                    if identifier in identities and identities[identifier] != source_url:
                        invalid += 1
                        index_invalid += 1
                        index_failed = True
                        reason = f'slug collision for {identifier!r} with {identities[identifier]}'
                        source_failed(source.url, reason)
                        if output_mode == 'db':
                            print(f'{name}: INVALID: {source.url}: {reason}', file=sys.stderr, flush=True)
                        continue

                    print(f'{name}: structuring with Claude: {source.url}', flush=True)
                    try:
                        opportunity = structure_listing(text, source, index_name=name, client=client, model=model)
                    except InvalidListingError as exc:
                        invalid += 1
                        index_invalid += 1
                        index_failed = index_failed or exc.operational_failure
                        source_failed(source.url, str(exc), phase='validation')
                        if output_mode == 'db':
                            print(f'{name}: INVALID: {source.url}: {exc}', file=sys.stderr, flush=True)
                        continue
                    except Exception as exc:
                        invalid += 1
                        index_invalid += 1
                        index_failed = True
                        source_failed(source.url, _error(exc), phase='claude')
                        if output_mode == 'db':
                            print(f'{name}: INVALID: {source.url}: {_error(exc)}', file=sys.stderr, flush=True)
                        continue

                    record = opportunity.to_record()
                    if output_mode == 'db':
                        try:
                            save_opportunity(connection, opportunity, content_hash=article.hash)
                        except OpportunityStorageError as exc:
                            index_failed = True
                            source_failed(source.url, str(exc), phase='database_save')
                            print(f'{name}: DATABASE FAILED: {opportunity.id}: {exc}',
                                  file=sys.stderr, flush=True)
                            continue
                    else:
                        try:
                            text_export.write_records(path, [*records, record])
                        except (OSError, UnicodeError) as exc:
                            source_failed(source.url, f'output save: {_error(exc)}', phase='output_save')
                            raise
                    if decision is not None:
                        if output_mode == 'db':
                            # A nested transaction is only a savepoint; do not
                            # claim a successful commit on behalf of its caller.
                            if connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE:
                                decision(source.url, 'saved', current_hash=article.hash, destination='db')
                        else:
                            decision(source.url, 'saved', current_hash=article.hash,
                                     destination='text', history_advanced=False)
                    records.append(record)
                    identities[identifier] = source_url
                    valid += 1
                    if output_mode == 'txt':
                        print(f'PASS {source.url}', flush=True)
                    else:
                        print(f'{name}: VALID: {opportunity.id}', flush=True)
        except (OSError, UnicodeError) as exc:
            index_failed = True
            print(f'{name}: FILE FAILED: {path}: {_error(exc)}', file=sys.stderr, flush=True)

        if index_failed:
            failed += 1
        else:
            completed += 1
        counts = (f'{len(records)} PASS, {index_source_failures} FAIL' if output_mode == 'txt'
                  else f'{len(records)} valid, {index_invalid} invalid')
        print(f'{name}: {"FAILED" if index_failed else "COMPLETE"}: '
              f'{counts}; output={destination}', flush=True)

    counts = (f'{valid} PASS, {source_failures} FAIL' if output_mode == 'txt'
              else f'{extracted} listings extracted, {valid} valid, {invalid} invalid, '
                   f'{extraction_failed} extraction failures')
    print(f'Summary: {completed} indexes completed ({empty} empty), {failed} indexes failed, '
          f'{skipped} indexes skipped, {history_skipped} articles skipped; {counts}', flush=True)
    return int(bool(failed))


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('must be a positive integer') from exc
    if number <= 0:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log-file', type=Path, default=DEFAULT_LOG,
                        help='Article decision JSONL log (default: project output/logs/scraper.jsonl)')
    parser.add_argument('--fixtures', action='store_true',
                        help='Read bundled saved articles; call real Claude and write text output without PostgreSQL')
    parser.add_argument('--index', metavar='NAME', help='Exact index name (case-insensitive)')
    parser.add_argument('--text', '--txt', dest='text', action='store_true',
                        help='Write JSON-array .txt files and print source PASS/FAIL outcomes')
    parser.add_argument('--output-dir', type=Path,
                        help='Directory with --text or --fixtures (defaults: output/ or output/fixtures/)')
    parser.add_argument('--limit', type=_positive_int, metavar='N', help='Process at most N listings per index for development')
    parser.add_argument('--model', metavar='MODEL', help='Claude model ID (otherwise use CLAUDE_MODEL)')
    args = parser.parse_args(argv)

    if args.output_dir is not None and not (args.text or args.fixtures):
        parser.error('--output-dir requires --text or --fixtures')
    if args.model is not None and not args.model.strip():
        parser.error('--model must not be empty')

    try:
        load_environment()
        with ExitStack() as resources:
            decision_log = resources.enter_context(DecisionLog(args.log_file))
            fixtures = FixtureCollection() if args.fixtures else None
            connection = None
            if fixtures is not None:
                indexes = [(index['name'], index['url']) for index in fixtures.indexes]
            else:
                connection = resources.enter_context(connect_database(autocommit=True))
                indexes = load_active_indexes(connection)
            if args.index:
                available_names = [name for name, _ in indexes]
                indexes = [(name, url) for name, url in indexes
                           if name.casefold() == args.index.casefold()]
                if not indexes:
                    message = ('Unknown fixture index name. Available indexes: ' if fixtures is not None
                               else 'Unknown or inactive index name. Active indexes: ')
                    parser.error(message + ', '.join(available_names))
            if not indexes:
                print('No active indexes; nothing to collect.', flush=True)
                return 0
            if fixtures is not None and all(fixtures.skip_reason(url) is not None for _, url in indexes):
                for name, url in indexes:
                    print(f'{name}: SKIPPED ({fixtures.skip_reason(url)})', flush=True)
                print(f'Summary: {len(indexes)} skipped; 0 PASS, 0 FAIL', flush=True)
                return 0
            if fixtures is None:
                check_history_table(connection)
                if not args.text:
                    check_opportunity_table(connection)
            api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
            model = (args.model or os.getenv('CLAUDE_MODEL', '')).strip()
            if not api_key:
                raise ValueError('Set ANTHROPIC_API_KEY in .env or the environment')
            if not model:
                raise ValueError('Set CLAUDE_MODEL in .env or the environment, or pass --model')

            # This module's listing-level retry budget is the only API retry layer.
            with Anthropic(api_key=api_key, max_retries=0, timeout=CLAUDE_TIMEOUT_SECONDS) as client:
                if fixtures is not None:
                    print('Fixture input: saved pages only; real Claude calls incur API usage.', flush=True)
                    return compose_indexes(
                        indexes, None, args.output_dir or Path('output/fixtures'), args.limit,
                        client=client, model=model, output_mode='txt', fixtures=fixtures, decision_log=decision_log,
                    )
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        return compose_indexes(
                            indexes, browser, args.output_dir or Path('output'), args.limit,
                            client=client, model=model, output_mode='txt' if args.text else 'db',
                            connection=connection, decision_log=decision_log,
                        )
                    finally:
                        browser.close()
    except psycopg.Error:
        print('Composer failed: database operation failed.', file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f'Composer failed: {_error(exc)}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
