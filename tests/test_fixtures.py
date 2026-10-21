"""Local article replay and collection integrity; Claude and HTTP stay mocked."""

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as entrypoint
from scraper import extraction, pipeline
from scraper.config import PROJECT_DIR
from scraper.fixtures import FIXTURE_DIR, FixtureCollection, FixtureError
from scraper.models import Opportunity
from scraper.structuring import InvalidListingError, article_slug, canonical_source_url


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'output'
        self.url = 'https://example.com/water-consultation?version=2'
        self.html = b'<main><h1>Saved consultation</h1><p>Archived article text.</p></main>'
        self.asset = self.resource('article.html', self.html, self.url)
        self.article = dict(source_url=self.url, source_name='Example', title='Saved',
                            route='html', status='ready', html=self.asset, resources=[])
        self.index = dict(id=8, name='Example', url='https://example.com/projects', active=False,
                          coverage_reason='No usable archived article.', listings=[], articles=[self.article])
        self.write_manifest()
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def resource(self, name, body, url, content_type='text/html'):
        (self.root / name).write_bytes(body)
        return dict(path=name, sha256=hashlib.sha256(body).hexdigest(), url=url,
                    timestamp='20260501000000', content_type=content_type,
                    replay_url=f'https://web.archive.org/web/20260501000000id_/{url}')

    def write_manifest(self):
        (self.root / 'manifest.json').write_text(json.dumps(dict(version=1, indexes=[self.index])))

    def structured(self, text, source, **kwargs):
        return Opportunity(id=article_slug(source.url), title='Saved consultation',
                           sourceUrl=canonical_source_url(source.url), sourceOrg='Example',
                           fullText=[text], jurisdiction='Victoria', startDate=None,
                           submissionDeadline='2026-11-01T00:00:00Z',
                           category=['Water & resources'], tags=None)

    def run_cli(self, args=(), structure=None):
        collection = FixtureCollection(self.root)
        with patch('scraper.pipeline.FixtureCollection', return_value=collection), \
             patch('scraper.pipeline.load_environment'), \
             patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key', 'CLAUDE_MODEL': 'test-model'}, clear=True), \
             patch('scraper.pipeline.Anthropic') as client, \
             patch('scraper.pipeline.connect_database', side_effect=AssertionError('Database forbidden')) as database, \
             patch('scraper.pipeline.sync_playwright', side_effect=AssertionError('Browser forbidden')) as browser, \
             patch('scraper.discovery.traverse_index', side_effect=AssertionError('Discovery forbidden')), \
             patch('scraper.extraction.process_single_source', side_effect=AssertionError('Live extraction forbidden')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')), \
             patch('scraper.pipeline.structure_listing', side_effect=structure or self.structured) as claude, \
             redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            status = entrypoint.main(['--fixtures', '--output-dir', str(self.output), *args])
        database.assert_not_called()
        browser.assert_not_called()
        return status, claude, client

    def test_root_fixture_mode_uses_original_url_and_no_database_or_browser(self):
        status, claude, client = self.run_cli(['--index', 'EXAMPLE', '--limit', '1'])
        self.assertEqual(status, 0)
        self.assertEqual(claude.call_args.args[1].url, self.url)
        self.assertEqual(claude.call_args.args[0], 'Saved consultation\nArchived article text.')
        self.assertEqual(claude.call_args.kwargs['index_name'], 'Example')
        client.return_value.__exit__.assert_called_once()
        output = json.loads(next(self.output.glob('*.txt')).read_text())
        self.assertEqual(output[0]['sourceUrl'], self.url)
        self.assertIn(f'PASS {self.url}', self.stdout.getvalue())
        self.assertIn('1 PASS, 0 FAIL', self.stdout.getvalue())

    def test_both_text_flags_are_accepted_with_fixtures(self):
        for flag in ('--text', '--txt'):
            with self.subTest(flag=flag):
                self.assertEqual(self.run_cli([flag])[0], 0)

    def test_default_output_and_collection_paths(self):
        collection = FixtureCollection(self.root)
        with patch('scraper.pipeline.FixtureCollection', return_value=collection), \
             patch('scraper.pipeline.load_environment'), \
             patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test', 'CLAUDE_MODEL': 'model'}, clear=True), \
             patch('scraper.pipeline.Anthropic'), \
             patch('scraper.pipeline.compose_indexes', return_value=0) as compose:
            self.assertEqual(pipeline.main(['--fixtures']), 0)
        self.assertEqual(compose.call_args.args[2], Path('output/fixtures'))
        self.assertIsNone(compose.call_args.args[1])
        self.assertEqual(FIXTURE_DIR, PROJECT_DIR / 'tests/fixtures/wayback')

    def test_invocation_from_another_working_directory(self):
        with chdir(self.root):
            status, claude, _ = self.run_cli()
        self.assertEqual(status, 0)
        self.assertEqual(claude.call_count, 1)

    def test_credentials_are_required_but_database_is_not(self):
        collection = FixtureCollection(self.root)
        with patch('scraper.pipeline.FixtureCollection', return_value=collection), \
             patch('scraper.pipeline.load_environment'), patch.dict(os.environ, {}, clear=True), \
             patch('scraper.pipeline.Anthropic') as client, \
             patch('scraper.pipeline.connect_database') as database, \
             redirect_stderr(self.stderr):
            self.assertEqual(pipeline.main(['--fixtures']), 1)
        self.assertIn('ANTHROPIC_API_KEY', self.stderr.getvalue())
        client.assert_not_called()
        database.assert_not_called()

    def test_limit_and_canonical_deduplication(self):
        duplicate = dict(self.article, source_url=self.url + '#section')
        other_url = 'https://example.com/second'
        other = dict(self.article, source_url=other_url)
        self.index['articles'] = [self.article, duplicate, other]
        self.write_manifest()
        collection = FixtureCollection(self.root)
        self.assertEqual([s.url for s in collection.sources(self.index['url'])], [self.url, other_url])
        status, claude, _ = self.run_cli(['--limit', '1'])
        self.assertEqual(status, 0)
        self.assertEqual(claude.call_count, 1)
        self.assertIn('LIMITED RUN', self.stdout.getvalue())

    def test_missing_or_corrupt_selected_body_is_fail_without_claude(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    (self.root / 'article.html').unlink()
                else:
                    (self.root / 'article.html').write_bytes(b'Corrupt')
                status, claude, _ = self.run_cli()
                self.assertEqual(status, 1)
                claude.assert_not_called()
                self.assertNotIn('PASS https', self.stdout.getvalue())
                self.assertIn('FAIL https', self.stderr.getvalue())

    def test_unavailable_index_is_skip_without_credentials_or_output(self):
        self.index['articles'] = []
        self.write_manifest()
        collection = FixtureCollection(self.root)
        with patch('scraper.pipeline.FixtureCollection', return_value=collection), \
             patch('scraper.pipeline.load_environment'), patch.dict(os.environ, {}, clear=True), \
             patch('scraper.pipeline.Anthropic') as client, \
             patch('scraper.pipeline.connect_database') as database, \
             redirect_stdout(self.stdout):
            self.assertEqual(pipeline.main(['--fixtures']), 0)
        client.assert_not_called()
        database.assert_not_called()
        self.assertIn('SKIPPED (No usable archived article.)', self.stdout.getvalue())
        self.assertFalse(self.output.exists())

    def test_invalid_result_keeps_normal_exit_semantics(self):
        def invalid(*args, **kwargs):
            raise InvalidListingError('Missing deadline', attempts=1)
        status, _, _ = self.run_cli(structure=invalid)
        self.assertEqual(status, 0)
        self.assertIn('Missing deadline', self.stderr.getvalue())

    def test_operational_api_failure_is_nonzero(self):
        status, _, _ = self.run_cli(structure=Mock(side_effect=RuntimeError('API unavailable')))
        self.assertEqual(status, 1)
        self.assertIn('API unavailable', self.stderr.getvalue())

    def test_pass_only_after_save(self):
        with patch('scraper.text_export.write_records', side_effect=[None, OSError('Save failed')]):
            status, _, _ = self.run_cli()
        self.assertEqual(status, 1)
        self.assertNotIn('PASS https', self.stdout.getvalue())
        self.assertIn('output save', self.stderr.getvalue())

    def test_unknown_index_is_argument_error(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(['--index', 'Unknown'])
        self.assertEqual(caught.exception.code, 2)

    def test_pdf_selection_and_parser_use_local_bytes(self):
        html = b'<p>National Interest Analysis <a href="/web/20260501000000id_/https://example.com/analysis.pdf">PDF</a></p>'
        self.article.update(route='treaties', source_name=extraction.JOINT_TREATIES_SOURCE_NAME,
                            html=self.resource('treaty.html', html, self.url),
                            resources=[self.resource('analysis.pdf', b'%PDF fixture',
                                                     'https://example.com/analysis.pdf', 'application/pdf')])
        self.write_manifest()
        collection = FixtureCollection(self.root)
        document = Mock()
        document.__enter__ = Mock(return_value=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: 'PDF body')]))
        document.__exit__ = Mock(return_value=False)
        with patch('scraper.extraction.pdfplumber.open', return_value=document) as pdf:
            self.assertEqual(collection.extract(collection.sources(self.index['url'])[0], self.index['url']), 'PDF body')
        self.assertEqual(pdf.call_args.args[0].getvalue(), b'%PDF fixture')
        self.article['resources'] = []
        self.write_manifest()
        collection = FixtureCollection(self.root)
        with self.assertRaisesRegex(FixtureError, 'not listed'):
            collection.extract(collection.sources(self.index['url'])[0], self.index['url'])

    def test_other_special_pdf_routes_use_saved_documents(self):
        cases = [
            ('sarc', extraction.SARC_SOURCE_NAME,
             '<div class="tide-bill-intro__section-document"><h3>Introduction print – Bill</h3><a href="analysis.pdf">PDF</a></div>'),
            ('vewh', extraction.VEWH_SOURCE_NAME,
             '<a href="analysis.pdf" title="Section 1 Introduction">PDF</a>'),
        ]
        for route, name, html in cases:
            with self.subTest(route=route):
                self.article.update(route=route, source_name=name,
                                    html=self.resource('special.html', html.encode(), self.url),
                                    resources=[self.resource('analysis.pdf', b'%PDF fixture',
                                                             'https://example.com/analysis.pdf', 'application/pdf')])
                self.write_manifest()
                collection = FixtureCollection(self.root)
                with patch('scraper.extraction.pdfplumber.open') as pdf:
                    pdf.return_value.__enter__.return_value.pages = [SimpleNamespace(extract_text=lambda: 'Saved PDF text')]
                    source = collection.sources(self.index['url'])[0]
                    self.assertEqual(source.name, name)
                    self.assertEqual(collection.extract(source, self.index['url']), 'Saved PDF text')
                self.assertEqual(pdf.call_args.args[0].getvalue(), b'%PDF fixture')

    def test_manifest_rejects_escape_symlink_duplicate_and_unknown_route(self):
        for change in ('../outside.html', '/tmp/outside.html'):
            self.article['html']['path'] = change
            self.write_manifest()
            with self.assertRaisesRegex(FixtureError, 'escapes'):
                FixtureCollection(self.root)
        self.article['html']['path'] = 'linked.html'
        (self.root / 'linked.html').symlink_to('/tmp/outside.html')
        self.write_manifest()
        with self.assertRaisesRegex(FixtureError, 'escapes'):
            FixtureCollection(self.root)
        self.article['html']['path'] = 'article.html'
        self.article['route'] = 'live-download'
        self.write_manifest()
        with self.assertRaisesRegex(FixtureError, 'Unknown extraction route'):
            FixtureCollection(self.root)
        (self.root / 'manifest.json').write_text(json.dumps(dict(version=1, indexes=[self.index, self.index])))
        with self.assertRaises(FixtureError):
            FixtureCollection(self.root)


class BundledCollectionTests(unittest.TestCase):
    def test_coliban_samples_replay_through_the_fixture_pipeline(self):
        collection = FixtureCollection()
        index = next(i for i in collection.indexes if i['name'] == 'Coliban Water')
        sources = collection.sources(index['url'])
        self.assertEqual(len(sources), 2)

        def structured(text, source, **kwargs):
            return Opportunity(
                id=article_slug(source.url), title='Archived Coliban consultation',
                sourceUrl=canonical_source_url(source.url), sourceOrg=index['name'],
                fullText=[text], jurisdiction='Victoria', startDate=None,
                submissionDeadline='2026-11-01T00:00:00Z',
                category=['Water & resources'], tags=None,
            )

        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
             patch('scraper.pipeline.load_environment'), \
             patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test', 'CLAUDE_MODEL': 'test-model'}, clear=True), \
             patch('scraper.pipeline.Anthropic') as client, \
             patch('scraper.pipeline.connect_database', side_effect=AssertionError('Database forbidden')), \
             patch('scraper.pipeline.sync_playwright', side_effect=AssertionError('Browser forbidden')), \
             patch('socket.create_connection', side_effect=AssertionError('Network forbidden')), \
             patch('scraper.pipeline.structure_listing', side_effect=structured) as claude, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            status = entrypoint.main(['--fixtures', '--index', index['name'], '--output-dir', directory])
            records = json.loads(next(Path(directory).glob('*.txt')).read_text())
        self.assertEqual(status, 0, stderr.getvalue())
        self.assertEqual(claude.call_count, 2)
        self.assertEqual([r['sourceUrl'] for r in records], [s.url for s in sources])
        self.assertTrue(all(r['fullText'][0].strip() for r in records))
        self.assertIn('2 PASS, 0 FAIL', stdout.getvalue())
        client.return_value.__exit__.assert_called_once()

    def test_bundled_path_does_not_depend_on_working_directory(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            self.assertEqual(FixtureCollection().root, FIXTURE_DIR)

    def test_all_seed_ids_and_resources_have_provenance_and_valid_checksums(self):
        collection = FixtureCollection()
        expected_ids = sorted(int(i) for i in re.findall(
            r'^  \((\d+),', (PROJECT_DIR / 'sql/seed_website_indexes.sql').read_text(), re.M))
        self.assertEqual(sorted(i['id'] for i in collection.indexes), expected_ids)
        for index in collection.indexes:
            self.assertLessEqual(len(index['articles']), 3)
            resources = [s['resource'] for s in index['listings'] if s.get('resource')]
            for article in index['articles']:
                resources += ([article['html']] if article.get('html') else []) + article['resources']
            for resource in resources:
                with self.subTest(index=index['id'], path=resource['path']):
                    self.assertIn('/' + resource['timestamp'], resource['replay_url'])
                    self.assertTrue('20251021' <= resource['timestamp'][:8] <= '20261021')
                    self.assertTrue(collection.read(resource))

    def test_ready_article_bodies_extract_without_external_access(self):
        collection = FixtureCollection()
        with patch('socket.create_connection', side_effect=AssertionError('Network forbidden')):
            for index in collection.indexes:
                for source in collection.sources(index['url']):
                    with self.subTest(index=index['id'], url=source.url):
                        self.assertTrue(collection.extract(source, index['url']).strip())

    def test_reviewed_extraction_fragments(self):
        collection = FixtureCollection()
        reviewed = 0
        for index in collection.indexes:
            for article in index['articles']:
                if article['status'] != 'ready' or not article.get('expected_text_contains'):
                    continue
                text = collection.extract(extraction.Source(article['source_name'], article['source_url']), index['url'])
                for fragment in article['expected_text_contains']:
                    with self.subTest(index=index['id'], fragment=fragment):
                        self.assertIn(fragment, text)
                reviewed += 1
        self.assertGreaterEqual(reviewed, 5)

    def test_archived_counterexamples_retain_additions_below_shared_items(self):
        collection = FixtureCollection()
        for index_id in (9, 16, 18, 21, 34):
            index = next(i for i in collection.indexes if i['id'] == index_id)
            lists = sorted([s for s in index['listings'] if s['role'] != 'pagination'],
                           key=lambda s: s['requested_timestamp'])
            found = False
            for old, new in zip(lists, lists[1:]):
                old_urls = {e['url'] for e in old['entries']}
                known_seen = False
                for entry in new['entries']:
                    if entry['url'] in old_urls:
                        known_seen = True
                    elif known_seen:
                        found = True
            with self.subTest(index=index_id):
                self.assertTrue(found)


class FixtureCheckoutTests(unittest.TestCase):
    def test_git_checkouts_preserve_html_json_checksums_and_pdf_bytes(self):
        collection = FixtureCollection()
        coliban = next(i for i in collection.indexes if i['id'] == 9)
        html = coliban['articles'][0]['html']
        pdf = next(r for index in collection.indexes for article in index['articles']
                   for r in article['resources'] if r['content_type'] == 'application/pdf')
        sample_index = dict(coliban, listings=[], articles=[dict(coliban['articles'][0], resources=[pdf])])
        manifest = (json.dumps({'version': 1, 'indexes': [sample_index]}, indent=2) + '\n').encode()
        samples = {
            'manifest.json': manifest,
            html['path']: collection.read(html),
            pdf['path']: collection.read(pdf),
        }
        # Disable inherited Git-specific environment/config only in the temporary
        # repository; never change the user's repository or global Git settings.
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        for autocrlf in ('true', 'false'):
            with self.subTest(autocrlf=autocrlf), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)

                def git(*args):
                    return subprocess.run(
                        ['git', '-c', f'core.autocrlf={autocrlf}', *args],
                        cwd=repo, env=env, capture_output=True, check=True,
                    ).stdout

                git('init', '--quiet')
                (repo / '.gitattributes').write_bytes((PROJECT_DIR / '.gitattributes').read_bytes())
                fixture_root = repo / 'tests/fixtures/wayback'
                for name, raw in samples.items():
                    path = fixture_root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                git('add', '--', '.gitattributes', 'tests/fixtures/wayback')
                for name, raw in samples.items():
                    relative = f'tests/fixtures/wayback/{name}'
                    # Check Git's stored blobs as well as the checked-out files.
                    self.assertEqual(git('show', f':{relative}'), raw)
                    (fixture_root / name).unlink()
                git('checkout-index', '--all', '--force')
                for name, raw in samples.items():
                    self.assertEqual((fixture_root / name).read_bytes(), raw)
                replay = FixtureCollection(fixture_root)
                self.assertEqual(replay.read(html), samples[html['path']])
                self.assertEqual(replay.read(pdf), samples[pdf['path']])
                # Strict integrity checking still detects corruption after checkout.
                (fixture_root / html['path']).write_bytes(samples[html['path']] + b'changed')
                with self.assertRaisesRegex(FixtureError, 'checksum mismatch'):
                    replay.read(html)


if __name__ == '__main__':
    unittest.main()
