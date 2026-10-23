"""File-only article decisions. Never install a console logging handler."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scraper.config import PROJECT_DIR
from scraper.identity import canonical_source_url

DEFAULT_LOG = PROJECT_DIR / 'output' / 'logs' / 'scraper.jsonl'


def _safe_url(url):
    """Do not copy rejected URL credentials into the audit trail."""
    try:
        parts = urlsplit(url)
        sensitive = ('password', 'secret', 'token', 'api_key', 'apikey')
        if (parts.username is None and parts.password is None
                and not any(any(word in key.casefold() for word in sensitive)
                            for key, _ in parse_qsl(parts.query, keep_blank_values=True))):
            return url
        netloc = parts.netloc.rsplit('@', 1)[-1]
        query = [(key, '[redacted]' if any(word in key.casefold()
                  for word in sensitive) else value)
                 for key, value in parse_qsl(parts.query, keep_blank_values=True)]
        return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), ''))
    except ValueError:
        return '[invalid URL]'


class DecisionLogError(RuntimeError):
    """A decision could not be recorded; stop rather than lose the audit trail."""


class DecisionLog:
    def __init__(self, path=DEFAULT_LOG, *, run_id=None, stage=None):
        self.path = Path(path)
        self.run_id = run_id or uuid4().hex
        self.stage = stage
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open('a', encoding='utf-8', newline='\n')
        except (OSError, UnicodeError):
            raise DecisionLogError('Cannot open article decision log.') from None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self._file.close()
        except OSError:
            raise DecisionLogError('Cannot close article decision log.') from None

    def emit(self, index, index_url, source_url, decision, **fields):
        try:
            canonical = canonical_source_url(source_url)
        except ValueError:
            canonical = None
        # Only explicitly supplied, structured fields are logged. Exceptions and
        # article text are deliberately excluded to avoid leaking credentials.
        event = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                     run_id=self.run_id, stage=self.stage, index=index,
                     index_url=_safe_url(index_url), source_url=_safe_url(source_url),
                     canonical_url=_safe_url(canonical) if canonical else None,
                     decision=decision, **fields)
        try:
            self._file.write(json.dumps(event, ensure_ascii=False) + '\n')
            self._file.flush()
        except (OSError, UnicodeError):
            raise DecisionLogError('Cannot write article decision log.') from None

    def for_index(self, name, url):
        return lambda source_url, decision, **fields: self.emit(name, url, source_url, decision, **fields)
