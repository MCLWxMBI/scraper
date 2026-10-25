"""Stable filenames and atomic structured/raw text exports."""

import hashlib
import json
import re
import unicodedata
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit
from pathlib import Path
from tempfile import NamedTemporaryFile

from scraper.config import PROJECT_DIR
from scraper.identity import canonical_source_url

RAW_OUTPUT_DIR = PROJECT_DIR / 'output' / 'raw'


def index_filename(name: str, url: str) -> str:
    """Produce a portable filename, distinguishing indexes with similar names."""
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.casefold()).strip('-')[:80] or 'index'
    suffix = hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]
    return f'{slug}-{suffix}.txt'


def raw_article_path(index_name: str, index_url: str, source_url: str) -> Path:
    """Use URL identities, independent of Claude slugs and structured output_dir."""
    canonical = canonical_source_url(source_url)
    leaf = unquote(urlsplit(canonical).path.rstrip('/').rsplit('/', 1)[-1]) or 'article'
    return RAW_OUTPUT_DIR / Path(index_filename(index_name, index_url)).stem / index_filename(leaf, canonical)


@contextmanager
def _atomic_output(path: Path):
    """Replace only after a complete write; retain the previous file on failure."""
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp',
                                delete=False) as output:
            temporary = Path(output.name)
            yield output
            output.flush()
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_records(path: Path, records: list[dict]) -> None:
    """Atomically save a complete JSON array, retaining the last successful save."""
    with _atomic_output(path) as output:
        json.dump(records, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')


def write_raw(path: Path, text: str) -> None:
    """Save the exact normalized extractor text, without headers or added newlines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _atomic_output(path) as output:
        output.write(text)
