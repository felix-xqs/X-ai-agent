"""No dependency installation or external service is needed for these tests."""
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from server import planner as p
from server.api import routes, utils


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'queue.sqlite3'
        self.queue = p.Queue(self.path)
        self.config = dict(topic='AI learning', language='en', style='practical', count=3,
                           start_at='2030-01-01T09:00:00+08:00', interval_minutes=60)
        self.after = p.timestamp('2030-01-02T00:00:00Z')
        # These operations must never reach a network API, even if keys exist.
        self.no_network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        self.no_network.start()

    def tearDown(self):
        self.no_network.stop()
        self.queue.close()
        self.temp.cleanup()

    def test_languages_and_styles_produce_distinct_original_drafts(self):
        for language in ('en', 'zh'):
            for style in ('concise', 'practical', 'question'):
                posts = p.prepare(dict(self.config, language=language, style=style))
                self.assertEqual(len({item['text'] for item in posts}), 3)
                self.assertTrue(all('AI learning' in item['text'] for item in posts))

    def test_offsets_are_normalized_and_intervals_preserved(self):
        posts = p.prepare(self.config)
        self.assertEqual(posts[0]['scheduled_at'], '2030-01-01T01:00:00+00:00')
        self.assertEqual(posts[2]['scheduled_at'], '2030-01-01T03:00:00+00:00')

    def test_validation_rejects_bad_batch_before_writing(self):
        for change in ({'topic': ''}, {'topic': 1}, {'topic': 'x' * 121},
                       {'language': 'fr'}, {'style': 'reply'}, {'count': 4}, {'count': True},
                       {'interval_minutes': 0}, {'interval_minutes': 1.1},
                       {'start_at': '2030-01-01T09:00:00'}, {'start_at': 'bad'},
                       {'start_at': None}, {'provider': 'openai'}, {'password': 'secret'},
                       {'publisher': 'x'}):
            with self.subTest(change=change), self.assertRaises(p.PlannerError):
                self.queue.plan(dict(self.config, **change))
        self.assertEqual(self.queue.status()['posts'], [])
        for config in ([], None, 'text'):
            with self.assertRaises(p.PlannerError):
                p.prepare(config)

    def test_duplicate_prevention_ignores_case_unicode_and_whitespace(self):
        self.queue.plan(self.config)
        result = self.queue.plan(dict(self.config, topic='  ＡＩ   LEARNING  '))
        self.assertEqual(result, {'added': [], 'duplicates_skipped': 3})
        self.assertEqual(len(self.queue.status()['posts']), 3)
        self.assertEqual(self.queue.logs()[-1]['action'], 'duplicate_skipped')

    def test_duplicates_stay_blocked_after_success_and_restart(self):
        self.queue.plan(self.config)
        self.queue.run(self.after)
        self.queue.close()
        self.queue = p.Queue(self.path)
        self.assertEqual(self.queue.plan(self.config)['duplicates_skipped'], 3)
        self.assertEqual(self.queue.run(self.after)['results'], [])

    def test_due_boundary_and_future_posts(self):
        self.queue.plan(self.config)
        self.assertEqual(self.queue.run(p.timestamp('2030-01-01T00:59:59Z'))['results'], [])
        result = self.queue.run(p.timestamp('2030-01-01T01:00:00Z'))
        self.assertEqual(len(result['results']), 1)
        self.assertEqual([x['status'] for x in self.queue.status()['posts']], ['simulated', 'pending', 'pending'])

    def test_verified_receipts_are_saved_with_status_and_log(self):
        self.queue.plan(self.config)
        result = self.queue.run(self.after)
        self.assertEqual(len(result['results']), 3)
        for post in self.queue.status()['posts']:
            self.assertEqual(post['status'], 'simulated')
            self.assertEqual(post['attempts'], 1)
            self.assertTrue(p.verify(post, post['receipt']))
        self.assertEqual(self.queue.logs()[-1]['action'], 'simulation_verified')

    def test_error_and_mismatched_receipt_pause_remaining_items(self):
        for outcome in ('error', 'mismatch'):
            with self.subTest(outcome=outcome):
                self.queue.plan(self.config)
                result = self.queue.run(self.after, outcome)
                self.assertTrue(result['paused'])
                posts = self.queue.status()['posts']
                self.assertEqual([x['status'] for x in posts], ['failed', 'pending', 'pending'])
                self.assertIsNone(posts[0]['receipt'])
                self.assertEqual(self.queue.run(self.after)['results'], [])
                self.queue.retry(posts[0]['id'])
                self.queue.set_pause(False)

    def test_pause_is_persistent_and_resume_does_not_run(self):
        self.queue.plan(self.config)
        self.queue.set_pause(True)
        self.queue.close()
        self.queue = p.Queue(self.path)
        self.assertTrue(self.queue.paused)
        self.assertEqual(self.queue.run(self.after)['results'], [])
        self.queue.set_pause(False)
        self.assertTrue(all(x['attempts'] == 0 for x in self.queue.status()['posts']))

    def test_retry_is_explicit_and_does_not_resume(self):
        self.queue.plan(self.config)
        self.queue.run(self.after, 'error')
        self.queue.retry(1)
        self.assertTrue(self.queue.paused)
        self.assertEqual(self.queue.plan(self.config)['duplicates_skipped'], 3)
        self.queue.set_pause(False)
        self.queue.run(self.after)
        self.assertEqual(self.queue.status()['posts'][0]['attempts'], 2)
        with self.assertRaises(p.PlannerError):
            self.queue.retry(1)
        with self.assertRaises(p.PlannerError):
            self.queue.retry(999)

    def test_unexpected_exception_rolls_back_batch(self):
        self.queue.plan(self.config)
        original = p.Simulator.publish
        def crash(simulator, post):
            if post['id'] == 2:
                raise RuntimeError('interrupted')
            return original(simulator, post)
        with patch.object(p.Simulator, 'publish', crash), self.assertRaises(RuntimeError):
            self.queue.run(self.after)
        self.assertTrue(all(post['status'] == 'pending' and post['attempts'] == 0
                            for post in self.queue.status()['posts']))
        self.assertEqual(len(self.queue.run(self.after)['results']), 3)

    def test_receipt_verification_rejects_forged_result(self):
        self.queue.plan(self.config)
        post = self.queue.status()['posts'][0]
        good = p.Simulator().publish(post)
        for change in ({'id': 'real-1'}, {'mode': 'live'}, {'text': 'other'}, {'fingerprint': 'bad'}):
            self.assertFalse(p.verify(post, dict(good, **change)))
        self.assertFalse(p.verify(post, None))

    def test_real_publisher_and_legacy_browser_helpers_fail_closed(self):
        with self.assertRaises(p.PlannerError):
            p.DisabledPublisher().publish({'text': 'never publish'})
        for function in (routes.login_x, routes.run_agent, routes.get_session,
                         utils.setup_browser, utils.setup_agent):
            with self.assertRaisesRegex(RuntimeError, 'disabled'):
                asyncio.run(function())

    def test_client_browser_routes_have_no_external_calls(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('context', 'session', 'live-view'):
            route = (root / 'client/src/app/api' / name / 'route.ts').read_text()
            self.assertIn('status: 410', route)
            for forbidden in ('Browserbase', 'fetch(', 'chromium', 'process.env'):
                self.assertNotIn(forbidden, route)
        page = (root / 'client/src/app/page.tsx').read_text()
        self.assertNotIn('Sidebar', page)
        self.assertNotIn('ChatArea', page)

    def cli(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = p.main(['--db', str(self.path)] + list(args))
        return code, json.loads(output.getvalue())

    def test_cli_plan_status_run_logs_and_failure_exit_codes(self):
        config_path = Path(self.temp.name) / 'config.json'
        config_path.write_text(json.dumps(self.config))
        self.assertEqual(self.cli('plan', '--config', str(config_path))[0], 0)
        self.assertFalse(self.cli('status')[1]['real_publishing_enabled'])
        self.assertEqual(self.cli('dry-run', '--at', '2030-01-02T00:00:00Z', '--simulate', 'mismatch')[0], 1)
        self.assertEqual(self.cli('dry-run')[0], 1)
        self.assertEqual(self.cli('retry', '1')[0], 0)
        self.assertEqual(self.cli('resume')[0], 0)
        self.assertEqual(self.cli('dry-run', '--at', '2030-01-02T00:00:00Z')[0], 0)
        self.assertTrue(self.cli('logs')[1])
        self.assertEqual(self.cli('pause')[0], 0)

    def test_cli_invalid_json_and_missing_files_report_errors(self):
        config = Path(self.temp.name) / 'broken.json'
        config.write_text('{broken')
        for args in (('plan', '--config', str(config)), ('plan', '--config', 'missing.json'),
                     ('dry-run', '--at', 'not-a-date'), ('retry', '42')):
            code, result = self.cli(*args)
            self.assertEqual(code, 2)
            self.assertIn('error', result)

    def test_concurrent_manual_runs_do_not_process_items_twice(self):
        from concurrent.futures import ThreadPoolExecutor
        self.queue.plan(self.config)
        def run():
            queue = p.Queue(self.path)
            try:
                return queue.run(self.after)
            finally:
                queue.close()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: run(), range(2)))
        self.assertEqual(sum(len(result['results']) for result in results), 3)
        self.assertTrue(all(post['attempts'] == 1 for post in self.queue.status()['posts']))

    def test_runtime_uses_only_standard_library_imports(self):
        import ast
        source = Path(p.__file__).read_text()
        imports = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split('.')[0])
        self.assertEqual(imports - {'argparse', 'datetime', 'hashlib', 'json', 'pathlib', 'sqlite3', 'unicodedata'}, set())


if __name__ == '__main__':
    unittest.main()
