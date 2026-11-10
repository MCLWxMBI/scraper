"""Upload a local run checkpoint independently of collection and Claude."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from scraper.config import ConfigurationError, load_environment
from scraper.db.connection import connect_database
from scraper.run_results import RunResults, utc_now


def read_results(path: Path, outcome: str, job_status: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        started = datetime.fromisoformat(data['started_at'])
        if started.tzinfo is None:
            raise ValueError('Expected a timezone')
        for key in ('sources', 'extracted_opportunities'):
            if not isinstance(data[key], list) or any(not isinstance(item, dict) for item in data[key]):
                raise ValueError('Expected arrays of objects')
        if data['status'] not in ('running', 'passed', 'failed', 'interrupted'):
            raise ValueError('Invalid status')
        if data.get('finished_at') is not None:
            finished = datetime.fromisoformat(data['finished_at'])
            if finished.tzinfo is None or finished < started:
                raise ValueError('Invalid finish time')
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        print('Run results unavailable or invalid; uploading a minimal run summary.', file=sys.stderr)
        data = dict(started_at=os.environ.get('SCRAPER_RUN_STARTED_AT') or utc_now(),
                    finished_at=None, status='running', sources=[], extracted_opportunities=[])

    cancelled = outcome == 'cancelled' or job_status == 'cancelled'
    if cancelled:
        data['status'] = 'interrupted'
    elif outcome != 'success' or data['status'] == 'running':
        data['status'] = 'failed'
    data['finished_at'] = data.get('finished_at') or utc_now()
    for source in data['sources']:
        if source.get('status') == 'running':
            source['status'] = 'failed'
            source['error'] = 'Run stopped before this source completed.'
    return data


def upload_results(data: dict) -> None:
    # Retry connection establishment only. Once INSERT/COMMIT starts, a lost
    # connection can leave the outcome unknown; retrying could duplicate the row.
    connection = connect_database()
    with connection:
        connection.execute("SET LOCAL statement_timeout = '20s'")
        connection.execute('''
            INSERT INTO public.scraper_runs (
                started_at, finished_at, status, sources, extracted_opportunities
            ) VALUES (%s, %s, %s, %s, %s)
        ''', (data['started_at'], data['finished_at'], data['status'],
              Jsonb(data['sources']), Jsonb(data['extracted_opportunities'])))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('output/logs/run-results.json'))
    args = parser.parse_args(argv)
    try:
        data = read_results(args.results, os.environ.get('SCRAPER_STEP_OUTCOME', ''),
                            os.environ.get('SCRAPER_JOB_STATUS', ''))
        try:
            RunResults(args.results, data)
        except OSError:
            print('Could not retain run summary artifact; continuing database upload.', file=sys.stderr)
        load_environment()
        upload_results(data)
    except (ConfigurationError, psycopg.Error, ValueError, OSError):
        print('Run log upload failed; check database access and scraper_runs schema.',
              file=sys.stderr)
        return 1
    print('Scraper run log uploaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
