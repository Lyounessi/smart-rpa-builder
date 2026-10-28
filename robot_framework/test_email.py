import unittest

from .adapters.email import FakeEmailAdapter
from .base import BaseRobot
from .contracts import ExecutionCancelled, InputRow, RunOptions
from .email import EmailFailure, EmailStatus, EmailStep, make_message, referenced_fields, substitute
from .registry import Registry
from .runner import Runner
from .tests import Cancellation, Events, FakeBrowser


SPEC = EmailStep('notify_supplier', 'notifications', '{{email}}',
                 'Supplier {{supplier_name}} created', 'Hello {{supplier_name}}.')
VALUES = {'email':'fictional@example.invalid', 'supplier_name':'Fictional Alice'}


class EmailTests(unittest.TestCase):
    def run_robot(self, adapter, *, values=None, fields=None, checkpoint=True):
        self.events, self.log, self.cancel = Events(), [], Cancellation()
        class Robot(BaseRobot):
            email_steps = (SPEC,)

            def process(self, ctx, inputs):
                if checkpoint:
                    ctx.business_completed()
                ctx.email.send_step(SPEC, inputs)
        registry = Registry()
        registry.register('test', Robot)
        return Runner(registry, FakeBrowser(self.log), None, self.events, self.cancel, email=adapter).run(
            'test', [InputRow('1', VALUES if values is None else values)], RunOptions(email_timeout_seconds=3), input_fields=fields)

    def test_plain_substitution_and_non_executable_templates(self):
        self.assertEqual(referenced_fields(SPEC.subject), {'supplier_name'})
        self.assertEqual(substitute('{{supplier_name}}', {'supplier_name':'{{never_evaluate}}'}), '{{never_evaluate}}')
        for template in ['{{email.upper()}}', '{{email|safe}}', '{{__import__("os")}}', '{% for x in email %}', '{{email']:
            with self.assertRaises(ValueError):
                referenced_fields(template)
        with self.assertRaises(ValueError):
            substitute('{{missing}}', VALUES)

    def test_rendered_message_and_explicit_timeout(self):
        class CaptureAdapter:
            def send(inner, message, *, timeout_seconds):
                self.assertEqual(message.account, 'notifications')
                self.assertEqual(message.to, ('fictional@example.invalid',))
                self.assertEqual(message.subject, 'Supplier Fictional Alice created')
                self.assertEqual(message.body, 'Hello Fictional Alice.')
                self.assertEqual(timeout_seconds, 3)
                self.assertNotIn('Fictional Alice', repr(message))
                return EmailStatus.ACCEPTED
        result = self.run_robot(CaptureAdapter())
        self.assertEqual(result.state, 'completed')
        self.assertEqual(result.rows[0].status, 'OK')
        self.assertTrue(result.rows[0].business_completed)
        events = [(kind, data.get('step'), data.get('action_status')) for kind, data in self.events.items]
        self.assertIn(('step_started', 'notify_supplier', None), events)
        self.assertIn(('email_finished', 'notify_supplier', 'accepted'), events)
        self.assertIn(('step_completed', 'notify_supplier', None), events)

    def test_simulation_and_failure_outcomes_never_retry(self):
        for status in EmailStatus:
            adapter = FakeEmailAdapter(status)
            result = self.run_robot(adapter)
            self.assertEqual(adapter.calls, 1)
            self.assertEqual(result.rows[0].status, 'ERROR' if status in {'failed', 'uncertain'} else 'OK')
            self.assertTrue(result.rows[0].business_completed)
            self.assertNotIn('Fictional', repr(result))
            self.assertEqual(result.unprocessed, [])
            if status in {'failed', 'uncertain'}:
                self.assertEqual(result.rows[0].failed_step, 'notify_supplier')

    def test_unknown_exception_is_uncertain_and_redacted(self):
        class Broken:
            calls = 0
            def send(inner, message, *, timeout_seconds):
                inner.calls += 1
                raise TimeoutError('password=private-secret recipient=fictional@example.invalid')
        adapter = Broken()
        result = self.run_robot(adapter)
        self.assertEqual(adapter.calls, 1)
        self.assertIsInstance(result.primary_error, EmailFailure)
        self.assertEqual(result.primary_error.status, 'uncertain')
        self.assertNotIn('private-secret', str(result.primary_error))
        self.assertIn(('email_finished', 'uncertain'), [(kind, data.get('action_status')) for kind, data in self.events.items])

    def test_schema_missing_fields_and_invalid_values_fail_before_browser_opens(self):
        for values, fields in [(VALUES, {'email'}), ({'email':'x@example.invalid'}, {'email','supplier_name'}),
                               ({**VALUES, 'email':'bad\r\nBcc:other@example.invalid'}, set(VALUES))]:
            adapter = FakeEmailAdapter()
            result = self.run_robot(adapter, values=values, fields=fields)
            self.assertEqual(result.state, 'failed')
            self.assertEqual(adapter.calls, 0)
            self.assertEqual(self.log, ['close'])

    def test_unconfigured_provider_fails_explicitly(self):
        result = self.run_robot(None)
        self.assertEqual(result.state, 'failed')
        self.assertEqual(result.primary_error.status, 'failed')

    def test_cancellation_is_preserved_and_delivery_becomes_uncertain(self):
        class CancelAdapter:
            def send(inner, message, *, timeout_seconds):
                raise ExecutionCancelled()
        result = self.run_robot(CancelAdapter())
        self.assertEqual(result.state, 'cancelled')
        self.assertEqual(result.rows, [])
        self.assertEqual(result.unprocessed, [])
        self.assertEqual(self.log[-1], 'close')

    def test_cancel_before_send_never_calls_adapter(self):
        from .context import RobotContext
        cancel, adapter = Cancellation(), FakeEmailAdapter()
        ctx = RobotContext(None, None, Events(), cancel, adapter)
        ctx.row = '1'
        with self.assertRaises(ExecutionCancelled):
            with ctx.step('notification'):
                cancel.cancel = True
                ctx.email.send(account='notifications', to=VALUES['email'], subject='Subject', body='Body')
        self.assertEqual(adapter.calls, 0)

    def test_addresses_and_headers_validate_without_exposing_values(self):
        valid = make_message('notifications', ['a@example.invalid', 'b@example.invalid'], 'Subject', 'Body\nText')
        self.assertEqual(len(valid.to), 2)
        for to, subject in [('', 'Subject'), ('not-address', 'Subject'), ('a@example.invalid', 'bad\nBcc:x')]:
            with self.assertRaises(ValueError):
                make_message('notifications', to, subject, 'body')

    def test_timeout_limits(self):
        for timeout in [0, -1, 121, float('nan')]:
            with self.assertRaises(ValueError):
                RunOptions(email_timeout_seconds=timeout)
