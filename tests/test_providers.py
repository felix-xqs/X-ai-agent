"""Synthetic credentials and mocked HTTP only; real sockets are forbidden."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

from server import planner as p
from server import providers as providers

DUMMY_KEY = 'synthetic-test-key-not-a-real-credential'


def completion(posts=None, **changes):
    message = {'role': 'assistant', 'content': json.dumps({'posts': posts or ['One original draft', 'Another original draft']})}
    return {'choices': [dict(message=message, finish_reason='stop', **changes)]}


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')
        self.read_limit = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, limit):
        self.read_limit = limit
        return self.body[:limit]


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.queue = p.Queue(Path(self.temp.name) / 'queue.sqlite3')
        self.model_config = dict(base_url='https://model.example.invalid/v1/', model='custom-chat',
                                 api_key_env='SYNTHETIC_PLANNER_TEST_KEY')
        self.config = dict(topic='AI learning', count=2, provider='openai-compatible',
                           model_config=self.model_config, start_at='2030-01-01T00:00:00Z')
        self.environment = patch.object(providers.os, 'environ', {'SYNTHETIC_PLANNER_TEST_KEY': DUMMY_KEY})
        self.environment.start()
        self.no_network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Real network forbidden'))
        self.no_network.start()
        self.opener_patch = patch.object(providers.request, 'build_opener')
        self.build = self.opener_patch.start()
        self.opener = self.build.return_value
        self.response = FakeResponse(completion())
        self.opener.open.return_value = self.response

    def tearDown(self):
        self.opener_patch.stop()
        self.no_network.stop()
        self.environment.stop()
        self.queue.close()
        self.temp.cleanup()

    def assert_rejected(self):
        with self.assertRaises(p.PlannerError) as caught:
            self.queue.plan(self.config)
        self.assertNotIn(DUMMY_KEY, str(caught.exception))
        self.assertNotIn(DUMMY_KEY, json.dumps(self.queue.logs()))
        self.assertEqual(self.queue.status()['posts'], [])
        self.assertEqual(self.queue.logs()[-1]['action'], 'generation_failed')
        return str(caught.exception)

    def test_success_constructs_expected_chat_request_without_persisting_credentials(self):
        self.assertEqual(len(self.queue.plan(self.config)['added']), 2)
        self.opener.open.assert_called_once()
        args, kwargs = self.opener.open.call_args
        req = args[0]
        self.assertEqual(req.full_url, 'https://model.example.invalid/v1/chat/completions')
        self.assertEqual(req.method, 'POST')
        self.assertEqual(req.get_header('Authorization'), 'Bearer ' + DUMMY_KEY)
        self.assertEqual(kwargs, {'timeout': 30})
        payload = json.loads(req.data)
        self.assertEqual(payload['model'], 'custom-chat')
        self.assertEqual(payload['max_tokens'], 1024)
        self.assertEqual(payload['temperature'], 0.7)
        self.assertEqual(payload['stream'], False)
        self.assertEqual(payload['n'], 1)
        self.assertEqual(json.loads(payload['messages'][1]['content']),
                         {'topic': 'AI learning', 'language': 'en', 'style': 'practical', 'count': 2})
        self.assertNotIn(DUMMY_KEY, req.data.decode())
        self.assertEqual(self.response.read_limit, providers.MAX_RESPONSE_BYTES + 1)
        self.assertTrue(self.response.closed)
        handlers = self.build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], providers.NoRedirect)
        self.assertNotIn(DUMMY_KEY, json.dumps(self.queue.status()))
        self.assertNotIn(DUMMY_KEY, json.dumps(self.queue.logs()))
        self.assertEqual(len(self.queue.run(p.timestamp('2030-01-02T00:00:00Z'))['results']), 2)

    def test_configured_limits_and_token_field_are_used(self):
        self.model_config.update(timeout_seconds=1.5, max_tokens=256, temperature=None,
                                 token_parameter='max_completion_tokens')
        self.queue.plan(self.config)
        payload = json.loads(self.opener.open.call_args.args[0].data)
        self.assertEqual(payload['max_completion_tokens'], 256)
        self.assertNotIn('max_tokens', payload)
        self.assertNotIn('temperature', payload)
        self.assertEqual(self.opener.open.call_args.kwargs['timeout'], 1.5)

    def test_model_config_validation_happens_before_credential_or_network_access(self):
        invalid = [None, [], {}, dict(self.model_config, api_key='never-inline'),
                   dict(self.model_config, model=''), dict(self.model_config, model=123),
                   dict(self.model_config, api_key_env='bad-name'),
                   dict(self.model_config, api_key_env=None)]
        for field, values in [('timeout_seconds', [True, 0, 121, 10 ** 1000, float('nan'), float('inf'), '30']),
                              ('max_tokens', [True, 63, 4097, 1.5, '1024']),
                              ('temperature', [False, -1, 3, 10 ** 1000, float('nan'), '0.5']),
                              ('token_parameter', ['arbitrary', None, []])]:
            invalid.extend(dict(self.model_config, **{field: value}) for value in values)
        with patch.object(providers.os, 'environ') as environment:
            for config in invalid:
                with self.subTest(config=config), self.assertRaises(p.PlannerError):
                    p.prepare(dict(self.config, model_config=config))
            environment.get.assert_not_called()
        self.build.assert_not_called()

    def test_base_url_validation_without_echoing_secrets(self):
        urls = ['', None, 'ftp://localhost/v1', 'http://remote.example/v1',
                'https://user:' + DUMMY_KEY + '@example.invalid/v1',
                'https://example.invalid/v1?key=' + DUMMY_KEY,
                'https://example.invalid/v1#' + DUMMY_KEY,
                'https://example.invalid/v1?', 'https://example.invalid/v1#',
                'https://example.invalid/\n' + DUMMY_KEY, 'https://例子.com/v1',
                'https://example.invalid:99999', 'https://example.invalid:bad',
                'https://[broken', 'https://example.invalid/v1/chat/completions',
                'https://api.x.com/v1', 'https://twitter.com/v1',
                'https://api.X.com./v1', 'https://example.invalid\\evil/v1']
        for url in urls:
            with self.subTest(url=url), self.assertRaises(p.PlannerError) as caught:
                p.prepare(dict(self.config, model_config=dict(self.model_config, base_url=url)))
            self.assertNotIn(DUMMY_KEY, str(caught.exception))
        self.build.assert_not_called()

    def test_loopback_http_and_https_custom_paths_are_allowed(self):
        for base in ('http://127.0.0.1:8080/v1', 'http://localhost:1234/v1',
                     'http://[::1]:1234/v1', 'https://model.example.invalid/custom/api'):
            self.assertEqual(providers.validate_model_config(dict(self.model_config, base_url=base))['base_url'], base)
        self.build.assert_not_called()

    def test_missing_or_invalid_environment_value_has_safe_error(self):
        for value in (None, '', DUMMY_KEY + '\r\n', 'bad key', 'x' * 4097):
            with patch.object(providers.os, 'environ', {'SYNTHETIC_PLANNER_TEST_KEY': value}):
                self.assert_rejected()
        self.build.assert_not_called()

    def test_mock_default_does_not_read_credentials_or_make_requests(self):
        with patch.object(providers.os, 'environ') as environment:
            posts = p.prepare({'topic': 'mock defaults'})
            environment.get.assert_not_called()
        self.assertEqual(len(posts), 3)
        self.build.assert_not_called()

    def test_mock_rejects_accidental_model_config(self):
        with self.assertRaises(p.PlannerError):
            p.prepare(dict(self.config, provider='mock'))
        self.build.assert_not_called()

    def test_timeout_dns_tls_and_transport_errors_are_redacted_without_retry(self):
        for exc in (TimeoutError(DUMMY_KEY), error.URLError(DUMMY_KEY),
                    OSError(DUMMY_KEY), providers.http.client.IncompleteRead(b'partial ' + DUMMY_KEY.encode())):
            self.opener.open.reset_mock()
            self.opener.open.side_effect = exc
            message = self.assert_rejected()
            self.assertIn('failed or timed out', message)
            self.opener.open.assert_called_once()

    def test_http_errors_are_redacted_and_do_not_read_response_body(self):
        for code in (301, 302, 307, 308, 400, 401, 403, 429, 500, 503):
            stream = io.BytesIO(DUMMY_KEY.encode())
            exc = error.HTTPError('https://example.invalid/' + DUMMY_KEY, code, DUMMY_KEY,
                                  {'Authorization': DUMMY_KEY}, stream)
            self.opener.open.side_effect = exc
            message = self.assert_rejected()
            self.assertIn(str(code), message)
            self.assertTrue(stream.closed)

    def test_redirect_handler_never_returns_a_followup_request(self):
        redirect = providers.NoRedirect()
        for code in (301, 302, 303, 307, 308):
            self.assertIsNone(redirect.redirect_request(None, None, code, 'moved', {}, 'https://other.invalid'))

    def test_non_200_success_status_is_rejected(self):
        self.response.status = 201
        self.assertIn('HTTP status', self.assert_rejected())

    def test_response_size_and_unicode_limits(self):
        for body in (b'x' * (providers.MAX_RESPONSE_BYTES + 10), b'\xff' + DUMMY_KEY.encode()):
            self.opener.open.return_value = FakeResponse(body)
            self.assert_rejected()

    def test_invalid_envelopes_are_rejected_with_no_body_in_errors_or_logs(self):
        envelopes = [b'not JSON ' + DUMMY_KEY.encode(), {}, [], None,
                     {'choices': []}, {'choices': [{}]}, {'choices': [None]},
                     {'choices': [completion()['choices'][0]] * 2}]
        for reason in ('length', 'content_filter', 'tool_calls', None):
            envelope = completion()
            envelope['choices'][0]['finish_reason'] = reason
            envelopes.append(envelope)
        for change in ({'role': 'user'}, {'tool_calls': [{'name': 'x'}]},
                       {'function_call': {'name': 'x'}}, {'refusal': DUMMY_KEY},
                       {'content': None}, {'content': [{'type': 'text', 'text': DUMMY_KEY}]},
                       {'content': DUMMY_KEY}):
            envelope = completion()
            envelope['choices'][0]['message'].update(change)
            envelopes.append(envelope)
        for envelope in envelopes:
            self.opener.open.return_value = FakeResponse(envelope)
            self.assert_rejected()

    def test_invalid_drafts_and_secret_echo_never_enter_queue(self):
        invalid = [None, [], {}, {'posts': ['One']}, {'posts': ['One', 'Two'], 'extra': True},
                   {'posts': ['One', None]}, {'posts': ['One', '']},
                   {'posts': ['One', 'x' * 281]}, {'posts': ['One', 'a\nb']}, {'posts': ['One', 'a\u2028b']}, {'posts': ['One', 'a\u2029b']},
                   {'posts': ['One', '\x1bescape']}, {'posts': ['One', '\ud800']},
                   {'posts': ['One', 'ＯＮＥ']}, {'posts': ['One', DUMMY_KEY]},
                   {'posts': ['One', 'prefix ' + DUMMY_KEY + ' suffix']}]
        for content in invalid:
            envelope = completion()
            envelope['choices'][0]['message']['content'] = json.dumps(content)
            self.opener.open.return_value = FakeResponse(envelope)
            self.assert_rejected()

    def test_nonstandard_json_and_duplicate_fields_are_rejected(self):
        for content in ('{"posts": ["One", "Two"], "posts": ["Other", "More"]}',
                        '{"posts": ["One", NaN]}', '{"posts": ["One", Infinity]}'):
            envelope = completion()
            envelope['choices'][0]['message']['content'] = content
            self.opener.open.return_value = FakeResponse(envelope)
            self.assert_rejected()
        raw = json.dumps(completion())
        self.opener.open.return_value = FakeResponse((raw[:-1] + ', "choices": []}').encode())
        self.assert_rejected()

    def test_response_read_timeout_is_sanitized(self):
        with patch.object(self.response, 'read', side_effect=TimeoutError(DUMMY_KEY)):
            self.assert_rejected()
        self.assertTrue(self.response.closed)

    def test_generation_failure_preserves_existing_posts_and_pause_state(self):
        self.queue.plan({'topic': 'Existing mock drafts'})
        before = self.queue.status()
        self.opener.open.side_effect = TimeoutError(DUMMY_KEY)
        with self.assertRaises(p.PlannerError):
            self.queue.plan(self.config)
        self.assertEqual(self.queue.status(), before)

    def test_cli_generates_once_and_returns_safe_error_with_no_traceback(self):
        config_file = Path(self.temp.name) / 'config.json'
        config_file.write_text(json.dumps(self.config))
        output = io.StringIO()
        with redirect_stdout(output):
            code = p.main(['--db', str(Path(self.temp.name) / 'cli.sqlite3'), 'plan', '--config', str(config_file)])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output.getvalue())['added']), 2)
        self.opener.open.assert_called_once()
        self.opener.open.side_effect = error.URLError(DUMMY_KEY)
        output = io.StringIO()
        with redirect_stdout(output):
            code = p.main(['--db', str(Path(self.temp.name) / 'cli.sqlite3'), 'plan', '--config', str(config_file)])
        self.assertEqual(code, 2)
        self.assertNotIn(DUMMY_KEY, output.getvalue())
        self.assertIn('error', json.loads(output.getvalue()))

    def test_invalid_schedule_never_triggers_model_request(self):
        with self.assertRaises(OverflowError):
            p.prepare(dict(self.config, start_at='9999-12-31T23:59:59Z'))
        self.build.assert_not_called()

    def test_provider_configuration_is_not_used_by_dry_run_status_or_logs(self):
        self.queue.plan({'topic': 'Only mock'})
        with patch.object(providers.os, 'environ') as environment:
            self.queue.run(p.timestamp('2030-01-01T00:00:00Z'))
            self.queue.status()
            self.queue.logs()
            environment.get.assert_not_called()
        self.build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
