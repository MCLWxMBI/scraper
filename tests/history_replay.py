"""Replay audited listing membership against real Compose PostgreSQL, without invoking Claude.

The manifest's ordered entries are the candidate input to production discovery
preparation. This is not a browser-pagination or historical-body reconstruction.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import signal
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin
from uuid import uuid4

import psycopg
from bs4 import BeautifulSoup
from psycopg import sql
from psycopg.conninfo import make_conninfo

from scraper import discovery
from scraper.config import PROJECT_DIR
from scraper.db.setup import seed_database
from scraper.db.history import load_history
from scraper.decision_log import DecisionLog
from scraper.fixtures import FixtureCollection, original_url
from scraper.identity import canonical_source_url, content_hash

# IDs are deliberately exhaustive, including inactive indexes. None means no
# bundled capture; unavailable resources retain their attempted timestamp.
SCHEDULE = {
    1: ('20251119213559', '20260211115141'),
    2: ('20251128084544', '20260210195336'),
    3: (None, '20260901032833'), 4: (None, '20260117154239'),
    5: (None, None), 6: ('20260211125204', '20260618080745'),
    7: ('20251106211959', '20251124151143'),
    8: ('20251123135332', '20251127203310'),
    9: ('20260505033327', '20260508113946'), 10: (None, None),
    11: (None, '20260410144026'),
    12: ('20260206200037', '20260512161933'),
    13: (None, '20260712064057'),
    14: ('20260710194154', '20260711204826'), 15: (None, None),
    16: ('20260216175709', '20260608150334'),
    17: (None, '20260611064417'),
    18: ('20260313135317', '20260615043943'),
    19: ('20260325212128', '20260421012845'),
    20: ('20260414113428', '20260614032742'),
    21: ('20251107140958', '20260412124944'),
    22: ('20260207015404', '20260617072451'),
    23: ('20251125091251', '20251205032038'),
    24: ('20260119135259', '20260419013113'),
    25: ('20251124193527', '20251220105836'),
    26: ('20260630062035', '20261001022315'),
    27: ('20260507025227', '20260804060123'),
    28: ('20260122164753', '20260423024735'),
    29: ('20260331023521', '20260510084900'),
    30: ('20260215211800', '20260322215629'),
    31: ('20260505052100', '20260518101405'),
    32: ('20260305231908', '20260618005400'),
    33: ('20260226162001', '20260507010819'),
    34: ('20251115214232', '20251126065001'),
    35: ('20260114233433', '20260308040406'),
    36: (None, '20260615111550'), 37: (None, None), 38: (None, None),
    39: ('20251101033227', '20260101033231'), 40: (None, None),
    41: ('20260710164505', '20260924143419'),
    42: ('20251112004508', '20251115093747'),
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def validate_resources(fixtures):
    """Check every reference, including repeated references, without modifying it."""
    paths = set()

    def visit(value):
        if isinstance(value, dict):
            if {'path', 'sha256', 'timestamp', 'replay_url'} <= value.keys():
                fixtures.read(value)
                require(value['timestamp'] in value['replay_url'], 'Capture provenance mismatch')
                require(value['replay_url'].startswith('https://web.archive.org/web/'),
                        'Expected archived resource provenance')
                paths.add(value['path'])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(fixtures.indexes)
    ids = [i['id'] for i in fixtures.indexes]
    require(len(ids) == 42 and set(ids) == set(SCHEDULE), 'Expected seed IDs 1–42 exactly once')
    return len(paths)


def listing(fixtures, index, timestamp):
    if timestamp is None:
        return None
    value = next((item for item in index['listings']
                  if item.get('resource', {}).get('timestamp', item['requested_timestamp']) == timestamp), None)
    require(value is not None, f'Capture {timestamp} is absent from manifest')
    if value['status'] != 'saved' or not value.get('resource'):
        return None
    raw = fixtures.read(value['resource']).decode('utf-8', errors='replace')
    soup = BeautifulSoup(raw, 'html.parser')
    links = set()
    for anchor in soup.select('a[href]'):
        url = original_url(urljoin(value['url'], anchor['href']))
        try:
            links.add(canonical_source_url(url))
        except ValueError:
            pass
    # Some listings supply server-side arrays instead of anchor cards. Check
    # their literal URL provenance as well, without fetching or running scripts.
    embedded = html.unescape(raw).replace('\\/', '/')
    for entry in value['entries']:
        key = canonical_source_url(entry['url'])
        require(key in links or entry['url'] in embedded,
                f'Listing entry has no saved HTML provenance: {entry["url"]}')
    return value


def make_case(fixtures, index, pair=None, section='main'):
    pair = pair or SCHEDULE[index['id']]
    # Do not try to validate a lone listing as a usable temporal pair.
    available = {item.get('resource', {}).get('timestamp')
                 for item in index['listings'] if item.get('resource') and item['status'] == 'saved'}
    old, new = ([listing(fixtures, index, ts) for ts in pair]
                if all(ts in available for ts in pair) else (None, None))
    case = dict(id=index['id'], name=index['name'], section=section,
                older=pair[0], newer=pair[1], status='skipped',
                reason='', stages=[], shared=[], additions=[])
    if old is None or new is None:
        case['reason'] = 'Missing usable older/newer listing file'
        return case, [], []
    ready = {canonical_source_url(s.url): s for s in fixtures.sources(index['url'])}
    old_keys = list(dict.fromkeys(canonical_source_url(e['url']) for e in old['entries']))
    new_keys = list(dict.fromkeys(canonical_source_url(e['url']) for e in new['entries']))
    if index['id'] in {24, 25}:
        # Inline/document routes have one stable source, not per-card identities.
        old_keys = new_keys = list(ready)
        case['note'] = 'Same saved inline/document body reused; historical equality is not asserted'
    shared = [key for key in new_keys if key in old_keys and key in ready][:2]
    additions = [key for key in new_keys if key not in old_keys and key in ready][:2]
    old_only = [key for key in old_keys if key not in new_keys and key in ready][:2]
    chosen = set(shared + additions + old_only)
    older = [ready[key] for key in old_keys if key in chosen]
    newer = [ready[key] for key in new_keys if key in chosen]
    case.update(shared=shared, additions=additions,
                listing_shared=len(set(old_keys) & set(new_keys)),
                listing_additions=len(set(new_keys) - set(old_keys)),
                unavailable_additions=[key for key in new_keys if key not in old_keys and key not in ready])
    if index['id'] == 1:
        case['note'] = 'Saved entries replace regionalhousing with apartmentrenewables; report wording differs'
    if index['id'] == 18:
        case['note'] = 'Shared-body history test only; mocked acceptance does not establish current opportunity eligibility'
    if not chosen:
        case['reason'] = 'No ready article bodies for these listings'
        if index['id'] == 41:
            for value in (old, new):
                raw = fixtures.read(value['resource']).decode('utf-8', errors='replace')
                text = BeautifulSoup(raw, 'html.parser').get_text(' ', strip=True).lower()
                require('there are currently no open consultations' in text,
                        'Expected explicit empty consultation state')
            case.update(status='empty', reason='Explicit empty open-consultation states; no deduplication claim')
        return case, older, newer
    complete = bool(shared and additions and not case['unavailable_additions'])
    case['status'] = 'passed' if complete else 'partial'
    case['reason'] = ('Unchanged and new article replay' if complete else
                      'Available samples only; see shared/additions and unavailable_additions')
    return case, older, newer


def run_case(fixtures, connection, index, log, case, older, newer):
    if case['status'] == 'skipped':
        return
    connection.execute('TRUNCATE public.opportunities, public.article_history')
    tracked = set()
    for stage, sources in [('older', older), ('newer', newer), ('newer_repeat', newer)]:
        log.stage = f'{case["section"]}:{stage}'
        keys = [canonical_source_url(source.url) for source in sources]
        expected = set(keys) - tracked
        before = dict(connection.execute('SELECT source_url, hash FROM public.article_history').fetchall())
        prepared = discovery.prepare_articles(
            sources, lambda source: fixtures.extract(source, index['url']),
            lambda urls: load_history(connection, urls),
            decision=log.for_index(index['name'], index['url']),
        )
        candidates = [article for article in prepared.articles if not article.skipped]
        require(all(article.error is None for article in prepared.articles),
                f'{index["id"]} {stage}: extraction failed')
        require({canonical_source_url(article.source.url) for article in candidates} == expected,
                f'{index["id"]} {stage}: unexpected processing candidates')
        # Discovery never advances history itself. These rows explicitly simulate
        # earlier successful processing, without inventing Claude responses or
        # running collection. Actual writer/trigger checks live in integration tests.
        require(dict(connection.execute('SELECT source_url, hash FROM public.article_history').fetchall()) == before,
                'Discovery changed history')
        with connection.transaction():
            for article in candidates:
                connection.execute("""
                    INSERT INTO public.article_history (source_url, title, hash)
                    VALUES (%s, %s, %s)
                """, (canonical_source_url(article.source.url), index['name'], article.hash))
        tracked.update(expected)
        rows = dict(connection.execute('SELECT source_url, hash FROM public.article_history').fetchall())
        require(set(rows) == tracked, f'{stage}: unexpected history identities')
        require(connection.execute('SELECT count(*) FROM public.opportunities').fetchone()[0] == 0,
                'Discovery-only test created opportunities')
        for source in sources:
            require(rows[canonical_source_url(source.url)] == content_hash(fixtures.extract(source, index['url'])),
                    f'{stage}: persisted hash differs')
        for key, digest in before.items():
            require(rows[key] == digest, f'{stage}: unchanged history mutated')
        events = [json.loads(line) for line in log.path.read_text().splitlines()]
        events = [event for event in events if event['run_id'] == log.run_id
                  and event['index_url'] == index['url'] and event['stage'] == log.stage]
        for key in keys:
            decisions = [event['decision'] for event in events if event['canonical_url'] == key]
            require(decisions == (['new'] if key in expected else ['unchanged']),
                    f'{stage}: incorrect decision log for {key}: {decisions}')
        case['stages'].append(dict(stage=stage, selected=len(keys), new=len(candidates),
                                   unchanged=len(keys) - len(candidates), history_rows_primed=len(expected)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', help='Exact fixture index name, case-insensitive')
    args = parser.parse_args(argv)
    fixtures = FixtureCollection()
    indexes = [i for i in fixtures.indexes if not args.index or i['name'].casefold() == args.index.casefold()]
    if not indexes:
        parser.error('Unknown fixture index name')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid4().hex[:8]
    directory = PROJECT_DIR / 'output' / 'history-replay' / run_id
    directory.mkdir(parents=True)
    summary = dict(run_id=run_id, resources=0, cases=[], error=None, database_removed=False,
                   body_policy='Reuse saved bodies; no historical body-equality claim', claude='not invoked; discovery only')
    admin = None
    database = 'scraper_history_replay_' + uuid4().hex
    summary['database'] = database
    created = False
    interrupted = lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt())
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        summary['resources'] = validate_resources(fixtures)
        dsn = os.environ.get('ARTICLE_HISTORY_TEST_DATABASE_URL',
                             'postgresql://scraper:scraper@postgres:5432/scraper')
        admin = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
        summary['postgres_version'] = admin.info.server_version
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        created = True
        with psycopg.connect(make_conninfo(dsn, dbname=database), autocommit=True,
                             options='-c lock_timeout=5000 -c statement_timeout=15000') as connection, \
             DecisionLog(directory / 'decisions.jsonl', run_id=run_id) as log:
            with connection.transaction():
                seed_database(connection)
            for index in indexes:
                comparisons = [(None, 'main')]
                if index['id'] == 12:
                    comparisons.append((('20251206125753', '20260411024308'), 'future'))
                for pair, section in comparisons:
                    case = None
                    try:
                        case, older, newer = make_case(fixtures, index, pair, section)
                        summary['cases'].append(case)
                        run_case(fixtures, connection, index, log, case, older, newer)
                    except Exception as exc:
                        if case is None:
                            summary['cases'].append(dict(id=index['id'], name=index['name'], section=section))
                        summary['cases'][-1].update(status='failed', reason='Database operation failed' if isinstance(exc, psycopg.Error) else type(exc).__name__ + ': ' + str(exc))
                    result = summary['cases'][-1]
                    print(f'{index["id"]:02} {index["name"]} [{section}]: {result["status"]}', flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        # Never serialize a database exception's detail/DSN into reports.
        summary['error'] = 'Database operation failed' if isinstance(exc, psycopg.Error) else type(exc).__name__
    finally:
        if admin is not None:
            try:
                if created:
                    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
                summary['database_removed'] = True
            except psycopg.Error:
                summary['error'] = 'Temporary database cleanup failed'
            finally:
                admin.close()
        signal.signal(signal.SIGTERM, previous)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    if summary['error']:
        print(f'Replay failed: {summary["error"]}', file=sys.stderr)
    print(f'Replay details: {directory}')
    return int(bool(summary['error'] or any(c['status'] == 'failed' for c in summary['cases'])))


if __name__ == '__main__':
    raise SystemExit(main())
