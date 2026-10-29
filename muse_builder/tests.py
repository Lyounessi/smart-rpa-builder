from io import StringIO
import json
from unittest.mock import Mock

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from openai import OpenAI

from .client import CHECK_MAX_OUTPUT_TOKENS, MetaClient, MetaConfiguration, MuseError


@override_settings(MUSE_APIKEY='fictional-test-key', META_MODEL='muse-spark-1.3', META_TIMEOUT_SECONDS='12')
class MetaClientTests(SimpleTestCase):
    def make_client(self, handler):
        self.requests, self.options = [], []
        def capture(request):
            self.requests.append(request)
            return handler(request)
        def factory(**kwargs):
            self.options.append(kwargs.copy())
            kwargs['http_client'] = httpx.Client(transport=httpx.MockTransport(capture), timeout=kwargs['timeout'], follow_redirects=False)
            return OpenAI(**kwargs)
        return MetaClient(client_factory=factory)

    def success(self, request, usage=True, text='OK', status='completed'):
        body = {'id':'resp_fictional', 'object':'response', 'created_at':0, 'model':'muse-spark-1.3',
            'status':status, 'output':[{'type':'message', 'id':'msg_fictional', 'role':'assistant', 'status':'completed',
            'content':[{'type':'output_text', 'text':text, 'annotations':[]}]}]}
        if usage:
            body['usage'] = {'input_tokens':12, 'output_tokens':5, 'total_tokens':17, 'input_tokens_details':{'cached_tokens':3}}
        return httpx.Response(200, json=body)

    def test_wire_request_fixed_host_small_prompt_and_no_retries(self):
        result = self.make_client(self.success).check_connection()
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(str(request.url), 'https://api.meta.ai/v1/responses')
        self.assertEqual(request.headers['authorization'], 'Bearer fictional-test-key')
        payload = json.loads(request.content)
        self.assertEqual(payload, {'model':'muse-spark-1.3', 'input':'Reply exactly OK.',
            'max_output_tokens':CHECK_MAX_OUTPUT_TOKENS, 'reasoning':{'effort':'minimal'}, 'store':False, 'tools':[]})
        self.assertNotIn('fictional-test-key', request.content.decode())
        self.assertEqual(self.options[0]['max_retries'], 0)
        timeout = self.options[0]['timeout']
        self.assertEqual(timeout.read, 12)
        self.assertEqual(timeout.connect, 10)
        self.assertFalse(self.options[0]['http_client'].follow_redirects)
        self.assertEqual(result.input_tokens, 12)
        self.assertEqual(result.output_tokens, 5)
        self.assertEqual(result.cached_tokens, 3)
        self.assertGreaterEqual(result.duration_seconds, 0)

    def test_missing_key_does_not_initialize_sdk(self):
        factory = Mock()
        with override_settings(MUSE_APIKEY=''), self.assertRaises(MuseError) as caught:
            MetaClient(client_factory=factory).check_connection()
        self.assertEqual(caught.exception.code, 'missing_key')
        factory.assert_not_called()

    def test_configuration_validation_and_secret_repr(self):
        self.assertNotIn('fictional-test-key', repr(MetaConfiguration.from_settings()))
        for values in [{'META_TIMEOUT_SECONDS':'nan'}, {'META_TIMEOUT_SECONDS':'0'}, {'META_TIMEOUT_SECONDS':'121'},
                       {'META_TIMEOUT_SECONDS':'wrong'}, {'META_MODEL':'model\ninvalid'}, {'MUSE_APIKEY':'invalid key'}]:
            with self.subTest(values=values), override_settings(**values), self.assertRaises(MuseError) as caught:
                MetaClient(client_factory=Mock()).check_connection()
            self.assertEqual(caught.exception.code, 'invalid_configuration')

    def test_provider_errors_redacted_and_never_retried(self):
        for status, code in [(400,'invalid_request'), (401,'authentication'), (402,'billing'), (403,'permission'),
                             (404,'model_not_found'), (429,'rate_limited'), (500,'provider'), (503,'provider')]:
            with self.subTest(status=status):
                client = self.make_client(lambda request: httpx.Response(status, json={
                    'error':{'message':'private-provider-data fictional-test-key', 'type':'server_error'}}))
                with self.assertRaises(MuseError) as caught:
                    client.check_connection()
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('private-provider-data', str(caught.exception))
                self.assertNotIn('fictional-test-key', str(caught.exception))
                self.assertEqual(len(self.requests), 1)

    def test_network_timeout_and_connection_error_are_distinct(self):
        for exception, code in [(httpx.ReadTimeout,'timeout'), (httpx.ConnectError,'connection')]:
            def handler(request):
                raise exception('private network diagnostics', request=request)
            client = self.make_client(handler)
            with self.assertRaises(MuseError) as caught:
                client.check_connection()
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('private network diagnostics', str(caught.exception))
            self.assertEqual(len(self.requests), 1)

    def test_redirect_is_not_followed(self):
        client = self.make_client(lambda request: httpx.Response(302, headers={'location':'https://other.example.invalid/'}))
        with self.assertRaises(MuseError):
            client.check_connection()
        self.assertEqual(len(self.requests), 1)

    def test_missing_usage_is_unavailable_not_zero(self):
        result = self.make_client(lambda request: self.success(request, usage=False)).check_connection()
        self.assertIsNone(result.input_tokens)
        self.assertIsNone(result.output_tokens)
        self.assertIsNone(result.cached_tokens)

    def test_unexpected_or_incomplete_response_not_silently_successful(self):
        for text, status in [('Other reply', 'completed'), ('', 'incomplete')]:
            client = self.make_client(lambda request: self.success(request, text=text, status=status))
            with self.assertRaises(MuseError) as caught:
                client.check_connection()
            self.assertEqual(caught.exception.code, 'unexpected_response')
            self.assertEqual(len(self.requests), 1)

    def test_command_outputs_only_safe_metadata_and_errors(self):
        from unittest.mock import patch
        output = StringIO()
        from types import SimpleNamespace
        with patch('muse_builder.management.commands.check_muse_connection.MuseService',
                   return_value=SimpleNamespace(check_connection=self.make_client(self.success).check_connection)):
            call_command('check_muse_connection', stdout=output)
        self.assertIn('Muse connection successful', output.getvalue())
        self.assertIn('input=12', output.getvalue())
        self.assertNotIn('fictional-test-key', output.getvalue())
        with override_settings(MUSE_APIKEY=''), self.assertRaises(CommandError) as caught:
            call_command('check_muse_connection')
        self.assertIn('[missing_key]', str(caught.exception))

    def test_structured_responses_use_text_format_schema(self):
        from .conversation_schema import provider_schema
        self.make_client(self.success).request(input='Review workflow', max_output_tokens=1536,
            instructions='Stable platform instructions', response_schema=provider_schema())
        payload = json.loads(self.requests[0].content)
        self.assertEqual(payload['text']['format']['type'], 'json_schema')
        self.assertTrue(payload['text']['format']['strict'])
        self.assertEqual(payload['instructions'], 'Stable platform instructions')
        self.assertNotIn('response_format', payload)
