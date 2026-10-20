"""Stable filenames and atomic JSON-array text exports."""

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from tempfile import NamedTemporaryFile


def index_filename(name: str, url: str) -> str:
    """Produce a portable filename, distinguishing indexes with similar names."""
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    slug = re.sub(r'[^a-z0-9]+', '-', ascii_name.casefold()).strip('-')[:80] or 'index'
    suffix = hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]
    return f'{slug}-{suffix}.txt'


def write_records(path: Path, records: list[dict]) -> None:
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


