"""Manifest-backed historical article input without browser or website access."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urldefrag, urljoin, urlsplit

from scraper import extraction
from scraper.config import PROJECT_DIR
from scraper.models import Source
from scraper.identity import canonical_source_url


FIXTURE_DIR = PROJECT_DIR / 'tests' / 'fixtures' / 'wayback'


class FixtureError(ValueError):
    """Missing, malformed or corrupt local fixture data."""


def original_url(url: str) -> str:
    """Remove a Wayback replay wrapper without altering meaningful queries."""
    match = re.search(r'/web/\d+(?:[a-z_]+)?/(https?://.*)', url)
    return urldefrag(match.group(1) if match else url)[0]


class FixtureCollection:
    def __init__(self, root: Path = FIXTURE_DIR):
        self.root = Path(root).resolve()
        try:
            manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
            if manifest['version'] != 1 or not isinstance(manifest['indexes'], list):
                raise ValueError('Unsupported manifest format')
            self.indexes = manifest['indexes']
            ids, names, urls = set(), set(), set()
            for index in self.indexes:
                if (type(index['id']) is not int or index['id'] in ids
                        or not isinstance(index['name'], str) or not index['name'].strip()
                        or index['name'].casefold() in names or index['url'] in urls):
                    raise ValueError('Duplicate or invalid fixture index')
                self._url(index['url'])
                ids.add(index['id'])
                names.add(index['name'].casefold())
                urls.add(index['url'])
                if not isinstance(index['articles'], list) or len(index['articles']) > 3:
                    raise ValueError('Expected at most three article samples per index')
                for listing in index['listings']:
                    if listing.get('resource'):
                        self._validate_resource(listing['resource'])
                for article in index['articles']:
                    self._url(article['source_url'])
                    if not isinstance(article['source_name'], str):
                        raise ValueError('Invalid source routing name')
                    if article['route'] not in {'html', 'sarc', 'treaties', 'vewh'}:
                        raise ValueError('Unknown extraction route')
                    if article['status'] not in {'ready', 'unavailable'}:
                        raise ValueError('Unknown article coverage status')
                    if article['status'] == 'ready' and 'html' not in article:
                        raise ValueError('Ready article is missing HTML')
                    for resource in ([article['html']] if 'html' in article else []) + article['resources']:
                        self._validate_resource(resource)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise FixtureError(f'Could not load fixture manifest: {exc}') from None
        self._by_url = {index['url']: index for index in self.indexes}

    @staticmethod
    def _url(url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in {'https', 'http'} or not parts.hostname or parts.username or parts.password:
            raise FixtureError('Fixture source must be an original HTTP(S) URL')

    def _path(self, resource: dict) -> Path:
        path = Path(resource['path'])
        resolved = (self.root / path).resolve()
        if path.is_absolute() or not resolved.is_relative_to(self.root):
            raise FixtureError('Fixture resource path escapes the collection directory')
        return resolved

    def _validate_resource(self, resource: dict) -> None:
        self._path(resource)
        self._url(resource['url'])
        if not re.fullmatch(r'[0-9a-f]{64}', resource['sha256']):
            raise FixtureError('Invalid fixture checksum')
        if not re.fullmatch(r'\d{14}', resource['timestamp']):
            raise FixtureError('Invalid fixture capture timestamp')
        if resource['content_type'] not in {'text/html', 'application/pdf'}:
            raise FixtureError('Unsupported fixture content type')

    def read(self, resource: dict) -> bytes:
        try:
            raw = self._path(resource).read_bytes()
        except OSError:
            raise FixtureError(f'Missing or unreadable fixture: {resource["path"]}') from None
        if hashlib.sha256(raw).hexdigest() != resource['sha256']:
            raise FixtureError(f'Fixture checksum mismatch: {resource["path"]}')
        return raw

    def skip_reason(self, index_url: str) -> str | None:
        index = self._by_url[index_url]
        if any(article['status'] == 'ready' for article in index['articles']):
            return None
        return index['coverage_reason']

    def sources(self, index_url: str) -> list[Source]:
        sources, seen = [], set()
        for article in self._by_url[index_url]['articles']:
            if article['status'] != 'ready':
                continue
            key = canonical_source_url(article['source_url'])
            if key not in seen:
                sources.append(Source(article['source_name'], article['source_url']))
                seen.add(key)
        return sources

    def extract(self, source: Source, index_url: str) -> str:
        article = next(a for a in self._by_url[index_url]['articles']
                       if a['status'] == 'ready' and a['source_url'] == source.url)
        html = self.read(article['html'])
        if article['route'] == 'html':
            return extraction.extract_page_text(html)
        # The production PDF selectors/parser receive a local-only request adapter.
        # Missing resources raise here; this adapter cannot perform HTTP requests.
        resources = {original_url(r['url']): r for r in article['resources']}

        def get(url: str, **kwargs):
            key = original_url(urljoin(article['html']['url'], url))
            if key not in resources:
                raise FixtureError(f'PDF is not listed in the fixture manifest: {key}')
            body = self.read(resources[key])
            return SimpleNamespace(ok=True, body=lambda: body)

        page = SimpleNamespace(url=article['html']['url'],
                               context=SimpleNamespace(request=SimpleNamespace(get=get)))
        selectors = {'sarc': extraction.extract_victorian_sarc_text,
                     'treaties': extraction.extract_joint_treaties_text,
                     'vewh': extraction.extract_vewh_text}
        return selectors[article['route']](page, html)
