"""Shared source identity and hashes of the exact normalized Claude input."""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_source_url(url: str) -> str:
    """Keep meaningful queries; use the inquiry page for treaty helper URLs."""
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
            or parts.password is not None or any(character.isspace() for character in url)):
        raise ValueError('Article URL must be an absolute HTTPS URL without credentials or whitespace')
    path = parts.path or '/'
    if ((parts.hostname or '').removeprefix('www.').casefold() == 'aph.gov.au'
            and '/joint/treaties/' in path.casefold()
            and path.rstrip('/').rsplit('/', 1)[-1].casefold() == 'treaty_being_considered'):
        path = path.rstrip('/').rsplit('/', 1)[0]
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.casefold().startswith('utm_')
             and key.casefold() not in {'fbclid', 'gclid', 'msclkid'}]
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, urlencode(query), ''))



def normalize_article_text(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_article_text(text).encode('utf-8')).hexdigest()
