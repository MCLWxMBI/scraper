"""Atomic local checkpoints for the separate GitHub Actions database upload."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunResults:
    def __init__(self, path: Path, data: dict | None = None):
        self.path = path
        self.data = data if data is not None else dict(
            started_at=utc_now(), finished_at=None, status='running',
            sources=[], extracted_opportunities=[])
        self.source = None
        self.titles = None
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.data, stream, ensure_ascii=False)
                stream.write('\n')
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def start_source(self, index) -> None:
        self.source = dict(website_index_id=index.id, source_name=index.name,
                           source_url=index.url, status='running', discovered_count=0,
                           processed_count=0, passed_count=0, invalid_count=0,
                           failed_count=0, skipped_count=0, error=None)
        self.titles = dict(website_index_id=index.id, source_name=index.name, titles=[])
        self.data['sources'].append(self.source)
        self.data['extracted_opportunities'].append(self.titles)
        self.save()

    def discovered(self, count: int) -> None:
        self.source['discovered_count'] = count
        self.save()

    def article(self, outcome: str, title: str | None = None) -> None:
        if outcome == 'skipped':
            self.source['skipped_count'] += 1
        else:
            self.source['processed_count'] += 1
            self.source[f'{outcome}_count'] += 1
            if outcome == 'passed':
                self.titles['titles'].append(title)
            elif outcome == 'failed':
                self.source['status'] = 'failed'
        self.save()

    def fail_source(self, reason: str) -> None:
        self.source['status'] = 'failed'
        self.source['error'] = reason
        self.save()

    def finish_source(self, status: str) -> None:
        if self.source['status'] != 'failed':
            self.source['status'] = status
        self.save()

    def finish(self, status: str) -> None:
        self.data['status'] = status
        self.data['finished_at'] = utc_now()
        for source in self.data['sources']:
            if source['status'] == 'running':
                source['status'] = 'failed'
                source['error'] = 'Run stopped before this source completed.'
        self.save()
