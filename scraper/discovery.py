"""Discover source pages for active database indexes without extracting text.

Run ``uv run python -m scraper discover`` or select one index with ``--index NAME``.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
import psycopg
from playwright.sync_api import Browser, Page, sync_playwright

from scraper import extraction
from scraper.config import ConfigurationError, load_environment
from scraper.decision_log import DecisionLogError
from scraper.run_log import RunLogError
from scraper.db.connection import DatabaseError, connect_database
from scraper.db.indexes import load_active_indexes
from scraper.db.history import ArticleHistory, HistoryError, load_history
from scraper.identity import canonical_source_url, content_hash, normalize_article_text

MAX_TRANSITIONS = 100
NAVIGATION_TIMEOUT = 45_000
LISTING_TIMEOUT = 15_000


class TraversalError(RuntimeError):
    """An index could not be traversed completely."""


@dataclass(frozen=True)
class PreparedArticle:
    source: extraction.Source
    text: str = ''
    hash: str | None = None
    skipped: str | None = None
    error: str | None = None
    invalid: bool = False


@dataclass(frozen=True)
class PreparedDiscovery:
    articles: list[PreparedArticle]
    discovered: int


HistoryLookup = Callable[[list[str]], dict[str, ArticleHistory]]


def prepare_articles(
    sources: list[extraction.Source],
    extract: Callable[[extraction.Source], str],
    history_lookup: HistoryLookup,
    *, limit: int | None = None, decision=None, refresh_locations: bool = False,
) -> PreparedDiscovery:
    """Discovery's content gate: no Claude calls and no history writes.

    Keep skipped/failed candidates for reporting, preserving Source routing.
    Only history errors propagate: they must stop the caller before paid work.
    """
    if limit is not None and limit <= 0:
        raise ValueError('limit must be positive')
    candidates, seen = [], set()
    for source in sources:
        try:
            key = canonical_source_url(source.url)
            error = None
        except ValueError as exc:
            key, error = source.url, str(exc)
        if key not in seen:
            seen.add(key)
            candidates.append((source, key, error))
    selected = candidates if limit is None else candidates[:limit]

    def log(source, outcome, **fields):
        if decision is not None:
            decision(source.url, outcome, **fields)

    try:
        history = history_lookup([key for _, key, error in selected if error is None]) if selected else {}
    except HistoryError:
        for source, _, _ in selected:
            log(source, 'failed', reason='history_lookup')
        raise
    prepared = []
    for source, key, error in selected:
        if error is not None:
            log(source, 'failed', reason='invalid_url')
            prepared.append(PreparedArticle(source, error=error, invalid=True))
            continue
        previous = history.get(key)
        if previous is not None and previous.deleted:
            log(source, 'deleted', previous_hash=previous.hash)
            prepared.append(PreparedArticle(source, skipped='deleted'))
            continue
        try:
            text = normalize_article_text(extract(source))
            if not text:
                raise ValueError('Extraction returned empty text')
            digest = content_hash(text)
        except (DecisionLogError, RunLogError):
            raise
        except Exception as exc:
            log(source, 'failed', reason='extraction')
            prepared.append(PreparedArticle(source, error=f'{type(exc).__name__}: {exc}'[:600]))
            continue
        if previous is not None and previous.hash == digest and not refresh_locations:
            log(source, 'unchanged', previous_hash=previous.hash, current_hash=digest)
            prepared.append(PreparedArticle(source, text=text, skipped='unchanged', hash=digest))
        else:
            log(source, 'refresh' if refresh_locations and previous is not None and previous.hash == digest
                else 'changed' if previous is not None and previous.hash else 'new',
                previous_hash=previous.hash if previous else None, current_hash=digest)
            prepared.append(PreparedArticle(source, text=text, hash=digest))
    return PreparedDiscovery(prepared, len(candidates))


def discover_articles(name: str, url: str, browser: Browser, connection: psycopg.Connection,
                      *, limit: int | None = None, decision=None, refresh_locations: bool = False) -> PreparedDiscovery:
    lookup = lambda urls: load_history(connection, urls)
    try:
        sources = traverse_index(name, url, browser, history_lookup=lookup)
    except HistoryError:
        if decision is not None:
            decision(url, 'failed', reason='history_lookup')
        raise

    def extract(source: extraction.Source) -> str:
        print(f'{name}: extracting during discovery: {source.url}', flush=True)
        return extraction.process_single_source(source, browser)

    return prepare_articles(sources, extract, lookup, limit=limit, decision=decision,
                            refresh_locations=refresh_locations)


def normalize_url(base_url: str, href: str) -> str | None:
    parts = urlsplit(urljoin(base_url, href))
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username:
        return None
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ''))


def _host(url: str) -> str:
    return (urlsplit(url).hostname or '').removeprefix('www.')


def _visible(anchor: Tag) -> bool:
    for element in [anchor, *anchor.parents]:
        if not isinstance(element, Tag):
            continue
        if element.name in {'nav', 'header', 'footer'} or element.get('role') == 'navigation':
            return False
        if element.get('data-traverse-visible') == 'false' or element.has_attr('hidden') or element.get('aria-hidden') == 'true':
            return False
        if re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', element.get('style', ''), re.I):
            return False
    return True


def _under_heading(soup: BeautifulSoup, pattern: str) -> tuple[list[Tag], bool, str]:
    """Read heading-bounded sections, including nested lower-level headings."""
    anchors: list[Tag] = []
    texts: list[str] = []
    found = False
    for heading in soup.select('h1,h2,h3,h4,h5,h6'):
        if not re.fullmatch(pattern, heading.get_text(' ', strip=True), re.I):
            continue
        found = True
        level = int(heading.name[1])
        for element in heading.next_elements:
            if isinstance(element, Tag):
                if re.fullmatch(r'h[1-6]', element.name) and int(element.name[1]) <= level:
                    break
                if element.name == 'a' and element.has_attr('href'):
                    anchors.append(element)
            elif str(element).strip():
                texts.append(str(element).strip())
    return anchors, found, ' '.join(texts)


EMPTY_PATTERN = re.compile(
    r'no (?:current |open |upcoming |matching )?(?:inquiries|consultations|projects|results|items)'
    r'|no inquiries in this list|there are currently no open consultations|showing 0|0 results|nothing found|no matches', re.I
)


@dataclass(frozen=True)
class Listing:
    selector: str
    accepts: Callable[[str], bool]
    heading: str | None = None
    consultation: bool = False
    paging: str = ''
    marker: str = ''
    heading_container: bool = False
    empty_allowed: bool = False
    required_status: str | None = None
    required_query: tuple[tuple[str, str], ...] = ()


def _card(anchor: Tag) -> Tag:
    if anchor.name == 'a' and any('card' in cls for cls in anchor.get('class', [])):
        return anchor
    for parent in anchor.parents:
        if isinstance(parent, Tag) and (
            parent.name in {'article', 'tr', 'li'}
            or any(cls in {'card', 'project-card', 'rpl-card-promo', 'views-row', 'inquiry', 'shadow-lg'} for cls in parent.get('class', []))
        ):
            return parent
    return anchor.parent if isinstance(anchor.parent, Tag) else anchor


def _excluded(anchor: Tag, consultation: bool) -> bool:
    card = _card(anchor)
    statuses = [e.get_text(' ', strip=True).casefold() for e in card.select(
        '[class*="status"], [class*="badge"], [class*="label"], td, .engage-consultation-end-date__text'
    )]
    # Entire card prose may describe a closed feedback phase on an ongoing project.
    forbidden = {'completed', 'complete', 'archived', 'past project'}
    if consultation:
        forbidden |= {'closed', 'submissions closed', 'reviewing feedback', 'reporting back'}
        if re.search(r'\bstatus\s*:\s*submissions closed\b', card.get_text(' ', strip=True), re.I):
            return True
    return any(status in forbidden or (consultation and re.match(r'^closed\b', status)) for status in statuses)


def project_card_status(anchor: Tag) -> str | None:
    """Read a project's explicit label without borrowing a neighbouring card's."""
    known = {'in planning', 'in progress', 'completed'}
    for parent in [anchor, *anchor.parents]:
        if not isinstance(parent, Tag) or parent.name in {'main', 'nav', 'header', 'footer', 'body', 'html'}:
            break
        labels = {node.get_text(' ', strip=True).casefold()
                  for node in parent.find_all(['div', 'span', 'p'])
                  if not node.find(['div', 'span', 'p'])} & known
        if labels:
            return next(iter(labels)) if len(labels) == 1 else None
    return None


def _parse_listing(html: str, page_url: str, spec: Listing) -> tuple[list[str], str]:
    soup = BeautifulSoup(html, 'html.parser')
    if spec.heading and spec.heading_container:
        headings = [h for h in soup.select('h1,h2,h3,h4,h5,h6') if re.fullmatch(spec.heading, h.get_text(' ', strip=True), re.I)]
        recognized = bool(headings)
        anchors = [a for heading in headings for a in heading.parent.select('a[href]')]
        section_text = ' '.join(h.parent.get_text(' ', strip=True) for h in headings)
    elif spec.heading:
        anchors, recognized, section_text = _under_heading(soup, spec.heading)
    else:
        anchors = list(soup.select(spec.selector))
        recognized = bool(anchors or (spec.marker and soup.select_one(spec.marker)))
        section_text = ' '.join(a.get_text(' ', strip=True) for a in anchors)
        if spec.marker:
            section_text += ' '.join(e.get_text(' ', strip=True) for e in soup.select(spec.marker))
    if not recognized:
        raise TraversalError(f'Expected listing section not found: {spec.heading or spec.selector}')
    raw: list[tuple[str, str]] = []
    accepted: list[str] = []
    status_seen = False
    for anchor in anchors:
        if not _visible(anchor):
            continue
        target = normalize_url(page_url, anchor.get('href', ''))
        if not target or not spec.accepts(target):
            continue
        raw.append((target, _card(anchor).get_text(' ', strip=True)))
        if not _excluded(anchor, spec.consultation):
            if spec.required_status is not None:
                status = project_card_status(anchor)
                status_seen |= status is not None
                if status != spec.required_status.casefold():
                    continue
            accepted.append(target)
    if raw and spec.required_status and not status_seen:
        raise TraversalError('Expected project-status labels not found')
    if not raw and not EMPTY_PATTERN.search(section_text) and not spec.empty_allowed:
        raise TraversalError('Listing exists but has no recognizable items or explicit empty state')
    current_page = [e.get_text(' ', strip=True) for e in soup.select(
        '.pagination .active, .pagination .uk-active, .pager__item--current, [aria-current="page"]'
    )]
    signature = hashlib.sha256(repr((raw, current_page)).encode()).hexdigest()
    return list(dict.fromkeys(accepted)), signature


def _snapshot(page: Page) -> str:
    # Browser visibility is authoritative for framework-controlled tabs and cards.
    page.locator('a[href]').evaluate_all('''(anchors) => anchors.forEach(a =>
        a.setAttribute('data-traverse-visible', String(!!a.getClientRects().length &&
            getComputedStyle(a).visibility !== 'hidden')))''')
    return page.content()


def _check_response(page: Page, response) -> None:
    if response is not None and response.status >= 400:
        raise TraversalError(f'HTTP {response.status}: {page.url}')
    text = page.locator('body').inner_text(timeout=LISTING_TIMEOUT)[:2500].casefold()
    if any(message in text for message in (
        'performing security verification', 'verify you are human', 'checking your browser',
        'access denied', 'request rejected', '403 forbidden',
    )) or page.title().casefold() == 'just a moment...':
        raise TraversalError(f'Browser verification or access block: {page.url}')
    if re.search(r'page not found|page cannot be found', page.title(), re.I):
        raise TraversalError(f'Page not found: {page.url}')


def _load(page: Page, url: str) -> None:
    response = page.goto(url, wait_until='domcontentloaded', timeout=NAVIGATION_TIMEOUT)
    if _host(page.url) != _host(url):
        raise TraversalError(f'Unexpected cross-domain redirect: {url} -> {page.url}')
    page.wait_for_function('document.body && document.body.innerText.trim().length > 0', timeout=LISTING_TIMEOUT)
    _check_response(page, response)


def _wait_listing(page: Page, spec: Listing, previous: str | None = None) -> tuple[list[str], str]:
    deadline = time.monotonic() + LISTING_TIMEOUT / 1000
    last_error = 'No listing content'
    stable: tuple[list[str], str] | None = None
    stable_since = 0.0
    while time.monotonic() < deadline:
        try:
            current = _parse_listing(_snapshot(page), page.url, spec)
            if current[1] != previous:
                if stable and stable[1] == current[1]:
                    if time.monotonic() - stable_since >= 0.75:
                        return current
                else:
                    stable, stable_since = current, time.monotonic()
            last_error = 'Pagination did not change the listing' if previous else last_error
        except TraversalError as exc:
            last_error = str(exc)
        page.wait_for_timeout(200)
    raise TraversalError(f'{last_error}: {page.url}')


def _next_control(page: Page, selector: str):
    if not selector:
        return None
    controls = page.locator(selector)
    for i in range(controls.count()):
        control = controls.nth(i)
        if control.is_visible() and control.is_enabled() and control.get_attribute('aria-disabled') != 'true':
            classes = control.get_attribute('class') or ''
            disabled_parent = control.evaluate('(e) => !!e.closest("[aria-disabled=true], .disabled, [disabled]")')
            if not disabled_parent and not re.search(r'\bdisabled\b|\bcursor-auto\b', classes):
                return control
    return None


def _collect(page: Page, spec: Listing) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    previous = None
    listing_path = urlsplit(page.url).path.rstrip('/')
    for transition in range(MAX_TRANSITIONS + 1):
        if spec.required_query:
            query = parse_qs(urlsplit(page.url).query)
            if any(query.get(key) != [value] for key, value in spec.required_query):
                raise TraversalError('Project-status filter was lost during pagination')
        batch, signature = _wait_listing(page, spec, previous)
        if signature in seen:
            raise TraversalError(f'Repeated listing page: {page.url}')
        seen.add(signature)
        urls.extend(batch)
        control = _next_control(page, spec.paging)
        if control is None:
            return list(dict.fromkeys(urls))
        if transition == MAX_TRANSITIONS:
            raise TraversalError(f'Exceeded {MAX_TRANSITIONS} pagination transitions: {page.url}')
        if control.evaluate('(e) => e.tagName') == 'A':
            target = normalize_url(page.url, control.get_attribute('href') or '')
            # Engage's server-rendered pager uses /?page=N for the /project listing.
            if target and _host(page.url) == 'engage.vic.gov.au' and urlsplit(target).path == '/' and _host(target) == _host(page.url):
                target = urlunsplit(('https', urlsplit(page.url).netloc, '/project', urlsplit(target).query, ''))
            target_path = urlsplit(target).path.rstrip('/') if target else ''
            allowed_path = (bool(re.fullmatch(re.escape(listing_path) + r'(?:/page/\d+)?', target_path))
                            if spec.required_query else target_path == urlsplit(page.url).path.rstrip('/'))
            if not target or _host(target) != _host(page.url) or not allowed_path:
                raise TraversalError('Pagination link left its listing route')
            if spec.required_query:
                parts = urlsplit(target)
                query = parse_qs(parts.query)
                if any(key in query and query[key] != [value] for key, value in spec.required_query):
                    raise TraversalError('Pagination changed the project-status filter')
                pairs = [(key, value) for key, value in parse_qsl(parts.query)
                         if key not in dict(spec.required_query)]
                target = urlunsplit(parts._replace(query=urlencode(pairs + list(spec.required_query))))
            _load(page, target)
        else:
            control.click(timeout=LISTING_TIMEOUT)
            _check_response(page, None)
        previous = signature
    raise AssertionError('Unreachable pagination state')


PAGER = 'a[rel="next"], .pager__item--next a, .pagination-next a, li.next a, .pagination a[title*="next" i], .pagination a[aria-label*="next" i]'
HIVE_HOSTS = {'letstalk.melbournewater.com.au', 'engage.yvw.com.au', 'connect.coliban.com.au', 'yoursay.lmw.vic.gov.au', 'haveyoursay.newater.com.au'}


def _same_site(page: Page, *prefixes: str) -> Callable[[str], bool]:
    host = _host(page.url)
    def accepts(target: str) -> bool:
        path = urlsplit(target).path.rstrip('/')
        return _host(target) == host and target != normalize_url(page.url, page.url) and (
            not prefixes or any(path.startswith(prefix) for prefix in prefixes)
        ) and not path.lower().endswith('.pdf')
    return accepts


def _named_link(page: Page, label: str, allowed_hosts: set[str]) -> str:
    links = page.get_by_role('link', name=re.compile(r'^' + re.escape(label) + r'(?:\s|$)', re.I))
    deadline = time.monotonic() + LISTING_TIMEOUT / 1000
    while time.monotonic() < deadline:
        for i in range(links.count()):
            link = links.nth(i)
            target = normalize_url(page.url, link.get_attribute('href') or '')
            if link.is_visible() and target and _host(target) in allowed_hosts:
                return target
        page.wait_for_timeout(200)
    raise TraversalError(f'Expected link not found: {label}')


def _sarc(page: Page) -> list[str]:
    parliament = {'parliament.vic.gov.au'}
    _load(page, _named_link(page, 'Scrutiny of Bills', parliament))
    _load(page, _named_link(page, 'Bills this week', parliament))
    _load(page, _named_link(page, 'Bills in Parliament', {'legislation.vic.gov.au'}))
    return _collect(page, Listing('.rpl-search-result__title a, .rpl-card__title a, main a[href*="/bills/"]',
        lambda url: _host(url) == 'legislation.vic.gov.au' and urlsplit(url).path.startswith('/bills/')
        and urlsplit(url).path.rstrip('/') not in {'/bills/in-parliament', '/bills/all-bills'}, paging=PAGER))


def _consultations(page: Page) -> list[str]:
    if urlsplit(page.url).path.rstrip('/') != '/find-consultations':
        # Industry's visible hub exposes these buttons; the generic nav is collapsed.
        _load(page, _named_link(page, 'Find open consultations', {_host(page.url)}))
    base = page.url.split('?', 1)[0]
    urls: list[str] = []
    for status in ('open', 'pending'):
        _load(page, base + '?status=' + status)
        urls.extend(_collect(page, Listing('table tbody a[href]', _same_site(page), consultation=True,
            marker='[data-clp-projectlist-table], [data-clp-projectlist]', paging='button[aria-label="Next"]')))
    return list(dict.fromkeys(urls))


def _federal(page: Page, treaties: bool, history_lookup: HistoryLookup | None = None) -> list[str]:
    prefix = urlsplit(page.url).path.rstrip('/') + '/'
    inquiries = _collect(page, Listing('[id$="ReferencesDiv"] li[id] a[href], [id$="LegislationDiv"] li[id] a[href]',
        _same_site(page, prefix), consultation=True,
        marker='[id$="ReferencesDiv"], [id$="LegislationDiv"]', empty_allowed=True))
    if not treaties:
        return inquiries
    history = history_lookup([canonical_source_url(url) for url in inquiries]) if history_lookup and inquiries else {}
    urls: list[str] = []
    for inquiry in inquiries:
        previous = history.get(canonical_source_url(inquiry))
        if previous is not None and previous.deleted:
            # Keep the candidate for limit/skip reporting, without visiting it.
            urls.append(inquiry)
            continue
        _load(page, inquiry)
        urls.append(_named_link(page, 'Treaty being considered', {'aph.gov.au'}))
    return urls


def project_listing(index_url: str) -> Listing | None:
    """Scoped project specs shared by browser discovery and saved-listing tests."""
    host, path = _host(index_url), urlsplit(index_url).path.rstrip('/')
    status = None
    required_query = ()
    if host == 'gippswater.com.au' and path == '/outages-works-and-projects/major-projects/future-major-projects':
        selector, prefix = '.card a[href]', path + '/'
    elif host == 'westernportwater.com.au' and path in {
        '/our-community/current-projects', '/our-community/projects/current-projects'
    }:
        selector = '#main .avia_textblock a[href], #content .avia_textblock a[href], .entry-content a[href]'
        prefix = '/our-community/projects/current-projects/'
    elif host == 'wannonwater.com.au' and path == '/community-and-environment/projects-and-initiatives':
        if parse_qs(urlsplit(index_url).query).get('filter_project_status[]') != ['223']:
            raise TraversalError('Wannon listing requires the In planning project-status filter (223)')
        selector, prefix = 'main a[href]', path + '/'
        status = 'In planning'
        required_query = (('filter_project_status[]', '223'),)
    else:
        return None

    def accepts(target: str) -> bool:
        target_path = urlsplit(target).path
        return (_host(target) == host and target_path.startswith(prefix)
                and target_path.rstrip('/') != prefix.rstrip('/')
                and not re.fullmatch(re.escape(prefix) + r'page/\d+/?', target_path)
                and not target_path.lower().endswith('.pdf'))

    return Listing(selector, accepts, paging=PAGER, required_status=status,
                   marker='main' if status else '', required_query=required_query)


def _dispatch(page: Page, requested_url: str, history_lookup: HistoryLookup | None = None) -> list[str]:
    host, path = _host(requested_url), urlsplit(requested_url).path.rstrip('/')
    if host == 'parliament.vic.gov.au':
        if path == '/sarc':
            return _sarc(page)
        if path in {'/epc-la', '/epc-lc'}:
            return _collect(page, Listing('', _same_site(page), heading='Current inquiries|Inquiries under way|Inquiries not yet accepting evidence', consultation=True))
    if host == 'aph.gov.au' and re.fullmatch(r'/Parliamentary_Business/Committees/(Senate|House|Joint)/[^/]+', path):
        return _federal(page, path.endswith('/Treaties'), history_lookup)
    if host in {'consult.industry.gov.au', 'consult.climatechangeauthority.gov.au', 'consult.dcceew.gov.au'} and path in {'', '/find-consultations'}:
        return _consultations(page)
    if host in HIVE_HOSTS and path == '/projects':
        return _collect(page, Listing('article.project a[href]', _same_site(page), paging='button.js-load-more-prj', marker='.projects-list'))
    if host == 'viccatchments.com.au' and path == '/priority-projects':
        if not page.get_by_role('heading', name='Priority Projects', exact=True).count():
            raise TraversalError('Priority Projects content not found')
        return [normalize_url(page.url, page.url)]
    if host == 'gvwater.vic.gov.au' and path == '/projects':
        _load(page, _named_link(page, 'Current Projects', {host}))
        accepts = _same_site(page, '/projects/')
        return _collect(page, Listing('.cp-detail a[href], .current-projects a[href], a:has(.cp-detail)',
            lambda target: accepts(target) and 'archiv' not in urlsplit(target).path.lower()))
    scoped = project_listing(requested_url)
    if scoped is not None:
        return _collect(page, scoped)
    if host == 'pc.gov.au' and path == '/inquiries-and-research':
        return _collect(page, Listing('', _same_site(page, '/inquiries-and-research/'), heading='Open for consultation|Upcoming consultations', consultation=True, heading_container=True))
    specs = {
        ('gww.com.au', '/faults-works/upgrades-projects/planned-works-projects'): Listing('main .view-display-id-major_projects_block a.linked-tile', _same_site(page), marker='.view-display-id-major_projects_block', paging=PAGER),
        ('southeastwater.com.au', '/faults-and-works/works/projects'): Listing('a.project-card', _same_site(page)),
        ('egwater.vic.gov.au', '/community/news'): Listing('.article-header h2 a', _same_site(page, '/community/news/'), paging=PAGER),
        ('gwmwater.org.au', '/building-and-development/projects/current-projects'): Listing('main a[href]', _same_site(page, '/building-and-development/projects/current-projects/')),
        ('sgwater.com.au', '/projects'): Listing('a.total-page, .project-news a[href]', _same_site(page, '/news/')),
        ('srw.com.au', '/initiatives/projects'): Listing('a.card__simple', _same_site(page, '/initiatives/projects/')),
        ('g-mwater.com.au', '/customer-services-resources/projects'): Listing('.item .title a[href]', lambda url: _host(url) == 'yoursay.gmwater.com.au'),
        ('esc.vic.gov.au', '/current-consultations'): Listing('.views-field-title a[href]', _same_site(page), consultation=True, paging=PAGER),
        ('ces.vic.gov.au', '/news'): Listing('.inner-wrapper a[href]', _same_site(page, '/news/'), paging=PAGER),
        ('engage.vic.gov.au', '/project'): Listing('.rpl-card-promo__title a[href]', _same_site(page), consultation=True, paging=PAGER),
        ('cer.gov.au', '/news-and-media/public-consultations'): Listing('', _same_site(page, '/news-and-media/public-consultations/'), heading='Current consultations', consultation=True),
        ('infrastructure.gov.au', '/have-your-say'): Listing('', _same_site(page, '/have-your-say/'), heading='Open consultations|Upcoming consultations', consultation=True, heading_container=True, paging=PAGER),
    }
    spec = specs.get((host, path))
    if spec is None:
        raise TraversalError(f'Unsupported index route: {requested_url}')
    return _collect(page, spec)


def traverse_index(name: str, url: str, browser: Browser, *,
                   history_lookup: HistoryLookup | None = None) -> list[extraction.Source]:
    """Discover a complete index; raise rather than return partial results."""
    page = browser.new_page()
    try:
        _load(page, url)
        urls = _dispatch(page, url, history_lookup) if history_lookup else _dispatch(page, url)
        source_name = name
        if _host(url) == 'parliament.vic.gov.au' and urlsplit(url).path.rstrip('/') == '/sarc':
            source_name = extraction.SARC_SOURCE_NAME
        elif _host(url) == 'aph.gov.au' and urlsplit(url).path.rstrip('/').endswith('/Joint/Treaties'):
            source_name = extraction.JOINT_TREATIES_SOURCE_NAME
        return [extraction.Source(source_name, target) for target in dict.fromkeys(urls)]
    except (TraversalError, HistoryError):
        raise
    except Exception as exc:
        raise TraversalError(f'{name}: {exc}') from exc
    finally:
        page.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', metavar='NAME', help='Exact index name (case-insensitive)')
    args = parser.parse_args(argv)
    try:
        load_environment()
        with connect_database(autocommit=True) as connection:
            selected = load_active_indexes(connection)
    except ConfigurationError as exc:
        print(f'Traversal failed: {exc}', file=sys.stderr, flush=True)
        return 1
    except psycopg.Error:
        print('Traversal failed: database operation failed.', file=sys.stderr, flush=True)
        return 1
    if args.index:
        active_names = [index.name for index in selected]
        selected = [index for index in selected if index.name.casefold() == args.index.casefold()]
        if not selected:
            parser.error('Unknown or inactive index name. Active indexes: ' + ', '.join(active_names))
    if not selected:
        print('No active indexes; nothing to collect.', flush=True)
        return 0
    results: dict[str, list[extraction.Source]] = {}
    failures: dict[str, str] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for index in selected:
                name, url = index.name, index.url
                try:
                    sources = traverse_index(name, url, browser)
                    results[name] = sources
                    print(f'{name}: {len(sources)} sources' if sources else f'{name}: EMPTY', flush=True)
                    for source in sources:
                        print(f'  {source.url}', flush=True)
                except TraversalError as exc:
                    failures[name] = str(exc)
                    print(f'{name}: FAILED: {exc}', file=sys.stderr, flush=True)
        finally:
            browser.close()
    print(f'{len(results)} indexes completed, {len(failures)} failed; {sum(map(len, results.values()))} sources', flush=True)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
