"""Traverse indexes, extract articles, and save Claude-structured JSON in .txt files.

Run ``uv run python composer.py`` or use ``--index NAME --limit 1`` for a small
development run. Output files are overwritten; collection history is not stored.
ANTHROPIC_API_KEY and CLAUDE_MODEL can be supplied in the project's .env file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile

from anthropic import Anthropic
from dotenv import load_dotenv
from playwright.sync_api import Browser, sync_playwright

import helpers
import traverse
from structuring import (
    CLAUDE_TIMEOUT_SECONDS,
    InvalidListingError,
    article_slug,
    canonical_source_url,
    structure_listing,
)


def index_filename(name: str, url: str) -> str:
    """Produce a portable filename, distinguishing indexes with similar names."""
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.casefold()).strip('-')[:80] or 'index'
    suffix = hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]
    return f'{slug}-{suffix}.txt'


def _error(exc: Exception) -> str:
    return f'{type(exc).__name__}: {exc}'[:600]


def _write_records(path: Path, records: list[dict]) -> None:
    """Atomically save a complete JSON array, retaining the last successful save."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp',
                                delete=False) as output:
            temporary = Path(output.name)
            json.dump(records, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write('\n')
            output.flush()
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def compose_indexes(
    indexes: Iterable[tuple[str, str]],
    browser: Browser,
    output_dir: str | Path,
    limit: int | None = None,
    *,
    client: Anthropic,
    model: str,
) -> int:
    """Write valid records per index and continue after invalid listings or errors.

    The caller owns the browser and API client. Helper Source objects are passed
    unchanged to extraction. Missing deadlines are normal invalid results; API,
    traversal, extraction, file errors and slug collisions cause a nonzero exit.
    """
    if limit is not None and limit <= 0:
        raise ValueError('limit must be a positive integer')
    output_dir = Path(output_dir)
    completed = failed = empty = skipped = extracted = valid = invalid = extraction_failed = 0
    identities: dict[str, str] = {}

    for name, url in indexes:
        if traverse.is_skipped(url):
            skipped += 1
            print(f'{name}: SKIPPED (past projects)', flush=True)
            continue

        path = output_dir / index_filename(name, url)
        index_failed = False
        index_invalid = 0
        records: list[dict] = []
        print(f'{name}: traversing; output={path}', flush=True)
        if limit is not None:
            print(f'{name}: DEVELOPMENT LIMIT: at most {limit} listings', flush=True)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            _write_records(path, records)
            try:
                sources = traverse.traverse_index(name, url, browser)
            except Exception as exc:
                index_failed = True
                print(f'{name}: TRAVERSAL FAILED: {_error(exc)}', file=sys.stderr, flush=True)
            else:
                selected = sources if limit is None else sources[:limit]
                print(f'{name}: {len(sources)} listings discovered, {len(selected)} selected', flush=True)
                if len(selected) < len(sources):
                    print(f'{name}: LIMITED RUN: remaining listings were intentionally not processed', flush=True)
                if not sources:
                    empty += 1
                    print(f'{name}: EMPTY: no listings discovered', flush=True)

                for number, source in enumerate(selected, start=1):
                    print(f'{name}: extracting {number}/{len(selected)}: {source.url}', flush=True)
                    try:
                        text = helpers.process_single_source(source, browser)
                        if not text.strip():
                            raise ValueError('Extraction returned empty text')
                    except Exception as exc:
                        extraction_failed += 1
                        index_failed = True
                        print(f'{name}: EXTRACTION FAILED: {source.url}: {_error(exc)}', file=sys.stderr, flush=True)
                        continue
                    extracted += 1

                    try:
                        source_url = canonical_source_url(source.url)
                        identifier = article_slug(source_url)
                    except ValueError as exc:
                        invalid += 1
                        index_invalid += 1
                        print(f'{name}: INVALID: {source.url}: {exc}', file=sys.stderr, flush=True)
                        continue
                    if identifier in identities and identities[identifier] != source_url:
                        invalid += 1
                        index_invalid += 1
                        index_failed = True
                        print(f'{name}: INVALID: {source.url}: slug collision for {identifier!r} '
                              f'with {identities[identifier]}', file=sys.stderr, flush=True)
                        continue

                    print(f'{name}: structuring with Claude: {source.url}', flush=True)
                    try:
                        opportunity = structure_listing(text, source, index_name=name, client=client, model=model)
                    except InvalidListingError as exc:
                        invalid += 1
                        index_invalid += 1
                        index_failed = index_failed or exc.operational_failure
                        print(f'{name}: INVALID: {source.url}: {exc}', file=sys.stderr, flush=True)
                        continue
                    except Exception as exc:
                        invalid += 1
                        index_invalid += 1
                        index_failed = True
                        print(f'{name}: INVALID: {source.url}: {_error(exc)}', file=sys.stderr, flush=True)
                        continue

                    record = opportunity.to_record()
                    _write_records(path, [*records, record])
                    records.append(record)
                    identities[identifier] = source_url
                    valid += 1
                    print(f'{name}: VALID: {opportunity.id}', flush=True)
        except (OSError, UnicodeError) as exc:
            index_failed = True
            print(f'{name}: FILE FAILED: {path}: {_error(exc)}', file=sys.stderr, flush=True)

        if index_failed:
            failed += 1
        else:
            completed += 1
        print(f'{name}: {"FAILED" if index_failed else "COMPLETE"}: '
              f'{len(records)} valid, {index_invalid} invalid; output={path}', flush=True)

    print(
        f'Summary: {completed} indexes completed ({empty} empty), {failed} indexes failed, '
        f'{skipped} skipped; {extracted} listings extracted, {valid} valid, {invalid} invalid, '
        f'{extraction_failed} extraction failures',
        flush=True,
    )
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
    parser.add_argument('--index', metavar='NAME', help='Exact index name (case-insensitive)')
    parser.add_argument('--output-dir', type=Path, default=Path('output'), help='JSON text file directory (default: output/)')
    parser.add_argument('--limit', type=_positive_int, metavar='N', help='Process at most N listings per index for development')
    parser.add_argument('--model', metavar='MODEL', help='Claude model ID (otherwise use CLAUDE_MODEL)')
    args = parser.parse_args(argv)

    indexes = traverse.INDEXES
    if args.index:
        indexes = [(name, url) for name, url in indexes if name.casefold() == args.index.casefold()]
        if not indexes:
            parser.error('Unknown index name. Use one of: ' + ', '.join(name for name, _ in traverse.INDEXES))
    if args.model is not None and not args.model.strip():
        parser.error('--model must not be empty')

    try:
        load_dotenv(dotenv_path=Path(__file__).resolve().with_name('.env'), override=False)
        api_key = os.getenv('ANTHROPIC_API_KEY', '').strip()
        model = (args.model or os.getenv('CLAUDE_MODEL', '')).strip()
        if not api_key:
            raise ValueError('Set ANTHROPIC_API_KEY in .env or the environment')
        if not model:
            raise ValueError('Set CLAUDE_MODEL in .env or the environment, or pass --model')

        # This module's listing-level retry budget is the only API retry layer.
        with Anthropic(api_key=api_key, max_retries=0, timeout=CLAUDE_TIMEOUT_SECONDS) as client:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    return compose_indexes(indexes, browser, args.output_dir, args.limit, client=client, model=model)
                finally:
                    browser.close()
    except Exception as exc:
        print(f'Composer failed: {_error(exc)}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
