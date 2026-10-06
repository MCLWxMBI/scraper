"""Traverse indexes and save each index's extracted listings in a UTF-8 text file.

Run ``uv run python composer.py`` or use ``--index NAME --limit 1`` for a small
development run. Output files are overwritten; collection history is not stored.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from playwright.sync_api import Browser, sync_playwright

import helpers
import traverse


def index_filename(name: str, url: str) -> str:
    """Produce a portable filename, distinguishing indexes with similar names."""
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.casefold()).strip('-')[:80] or 'index'
    suffix = hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]
    return f'{slug}-{suffix}.txt'


def _error(exc: Exception) -> str:
    return f'{type(exc).__name__}: {exc}'


def compose_indexes(
    indexes: Iterable[tuple[str, str]],
    browser: Browser,
    output_dir: str | Path,
    limit: int | None = None,
) -> int:
    """Write each index independently, continue on failures, and return an exit code.

    The caller owns the browser. Source objects are passed unchanged to the
    extraction helper, which owns and closes its individual pages.
    """
    if limit is not None and limit <= 0:
        raise ValueError('limit must be a positive integer')
    output_dir = Path(output_dir)
    completed = failed = empty = skipped = extracted = extraction_failed = 0

    for name, url in indexes:
        if traverse.is_skipped(url):
            skipped += 1
            print(f'{name}: SKIPPED (past projects)', flush=True)
            continue

        path = output_dir / index_filename(name, url)
        index_failed = False
        print(f'{name}: traversing; output={path}', flush=True)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with path.open('w', encoding='utf-8', newline='\n') as output:
                output.write(f'Index: {name}\nIndex URL: {url}\n')
                if limit is not None:
                    output.write(f'Development limit: at most {limit} listings for this index.\n')
                output.write('\n')
                output.flush()

                try:
                    sources = traverse.traverse_index(name, url, browser)
                except Exception as exc:
                    index_failed = True
                    message = _error(exc)
                    output.write(f'TRAVERSAL FAILED: {message}\n')
                    output.flush()
                    print(f'{name}: TRAVERSAL FAILED: {message}', file=sys.stderr, flush=True)
                else:
                    selected = sources if limit is None else sources[:limit]
                    output.write(f'Listings discovered: {len(sources)}\nListings selected: {len(selected)}\n')
                    if len(selected) < len(sources):
                        output.write('LIMITED RUN: remaining discovered listings were intentionally not extracted.\n')
                    if not sources:
                        empty += 1
                        output.write('EMPTY: no listings discovered.\n')
                        print(f'{name}: EMPTY', flush=True)
                    output.flush()

                    for number, source in enumerate(selected, start=1):
                        output.write(f'\n{"=" * 72}\nListing {number} of {len(selected)}\nSource URL: {source.url}\n\n')
                        output.flush()
                        print(f'{name}: extracting {number}/{len(selected)}: {source.url}', flush=True)
                        try:
                            text = helpers.process_single_source(source, browser)
                            if not text.strip():
                                raise ValueError('Extraction returned empty text')
                        except Exception as exc:
                            extraction_failed += 1
                            index_failed = True
                            message = _error(exc)
                            output.write(f'EXTRACTION FAILED: {message}\n')
                            output.flush()
                            print(f'{name}: EXTRACTION FAILED: {source.url}: {message}', file=sys.stderr, flush=True)
                        else:
                            output.write('EXTRACTION SUCCESS\n\n')
                            output.write(text)
                            output.write('\n')
                            output.flush()
                            extracted += 1

                output.write(f'\nIndex result: {"FAILED" if index_failed else "COMPLETE"}\n')
                output.flush()
        except (OSError, UnicodeError) as exc:
            index_failed = True
            print(f'{name}: FILE FAILED: {path}: {_error(exc)}', file=sys.stderr, flush=True)

        if index_failed:
            failed += 1
        else:
            completed += 1
            print(f'{name}: saved {path}', flush=True)

    print(
        f'Summary: {completed} indexes completed ({empty} empty), {failed} indexes failed, '
        f'{skipped} skipped; {extracted} listings extracted, {extraction_failed} extraction failures',
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
    parser.add_argument('--output-dir', type=Path, default=Path('output'), help='Text file directory (default: output/)')
    parser.add_argument('--limit', type=_positive_int, metavar='N', help='Extract at most N listings per index for development')
    args = parser.parse_args(argv)

    indexes = traverse.INDEXES
    if args.index:
        indexes = [(name, url) for name, url in indexes if name.casefold() == args.index.casefold()]
        if not indexes:
            parser.error('Unknown index name. Use one of: ' + ', '.join(name for name, _ in traverse.INDEXES))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                return compose_indexes(indexes, browser, args.output_dir, args.limit)
            finally:
                browser.close()
    except Exception as exc:
        print(f'Composer failed: {_error(exc)}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
