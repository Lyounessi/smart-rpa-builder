import unittest

from .base import BaseRobot
from .contracts import BusinessRejection, ExecutionCancelled, InputRow, RunOptions
from .registry import Registry, robot_name
from .runner import Runner


class FakeBrowser:
    def __init__(self, log):
        self.log = log

    def open(self, options):
        self.log.append('open_recorded' if options.record_screen else 'open')

    def close(self):
        self.log.append('close')
        return ['fictional.webm']

    def click(self, element):
        self.log.append('click')


class Events:
    def __init__(self):
        self.items = []

    def emit(self, kind, **data):
        self.items.append((kind, data))


class Cancellation:
    cancel = False

    def requested(self):
        return self.cancel


class FrameworkTests(unittest.TestCase):
    def execute(self, cls, **kwargs):
        self.log, self.events, self.cancel = [], Events(), Cancellation()
        registry = Registry()
        registry.register('ROBOT_TEST', cls)
        return Runner(registry, FakeBrowser(self.log), object(), self.events, self.cancel).run(
            'ROBOT_TEST', [InputRow('1', {'name':'Alice'}), InputRow('2', {'name':'Bob'})], RunOptions(**kwargs))

    def robot(self, failure=None, setup_failure=False, teardown_failure=False, recovery=True):
        test = self
        class Robot(BaseRobot):
            def setup(self, ctx):
                test.log.append('setup')
                if setup_failure:
                    raise RuntimeError('sensitive secret')

            def process(self, ctx, inputs):
                test.log.append('process')
                with ctx.step('submit'):
                    ctx.click('element-id')
                    if failure:
                        raise failure('sensitive secret')

            def recover(self, ctx, outcome):
                test.log.append('recover')
                return recovery

            def teardown(self, ctx):
                test.log.append('teardown')
                if teardown_failure:
                    raise RuntimeError('sensitive secret')
        return Robot

    def test_success_lifecycle_and_recording(self):
        result = self.execute(self.robot(), record_screen=True)
        self.assertEqual(self.log, ['open_recorded', 'setup', 'process', 'click', 'process', 'click', 'teardown', 'close'])
        self.assertEqual(result.state, 'completed')
        self.assertEqual([row.status for row in result.rows], ['OK', 'OK'])
        self.assertEqual(result.artifacts, ['fictional.webm'])
        self.assertEqual(self.events.items[-1][0], 'run_completed')

    def test_business_rejection_policies(self):
        result = self.execute(self.robot(failure=BusinessRejection), stop_on_nok=True)
        self.assertEqual(result.state, 'completed')
        self.assertEqual(result.unprocessed, ['2'])
        self.assertEqual(result.rows[0].status, 'NOK')
        result = self.execute(self.robot(failure=BusinessRejection))
        self.assertEqual(len(result.rows), 2)
        self.assertIn('recover', self.log)

    def test_technical_policies_and_recovery_required(self):
        result = self.execute(self.robot(failure=RuntimeError))
        self.assertEqual(result.state, 'failed')
        self.assertEqual(result.rows[0].failed_step, 'submit')
        self.assertNotIn('sensitive', repr(result))
        result = self.execute(self.robot(failure=RuntimeError), stop_on_error=False)
        self.assertEqual(result.state, 'completed')
        self.assertEqual(len(result.rows), 2)
        result = self.execute(self.robot(failure=BusinessRejection, recovery=False))
        self.assertEqual(result.state, 'failed')
        self.assertEqual(result.unprocessed, ['2'])

    def test_setup_and_teardown_failures(self):
        result = self.execute(self.robot(setup_failure=True, teardown_failure=True))
        self.assertEqual(self.log, ['open', 'setup', 'teardown', 'close'])
        self.assertEqual(result.state, 'failed')
        self.assertIn('Setup', result.message)
        self.assertEqual(result.cleanup_errors, ['Robot teardown failed.'])
        self.assertEqual(result.unprocessed, ['1', '2'])
        self.assertIsInstance(result.primary_error, RuntimeError)

    def test_processing_failure_preserved_when_teardown_also_fails(self):
        result = self.execute(self.robot(failure=ValueError, teardown_failure=True))
        self.assertEqual(result.state, 'failed')
        self.assertIsInstance(result.primary_error, ValueError)
        self.assertEqual(result.rows[0].status, 'ERROR')
        self.assertEqual(result.cleanup_errors, ['Robot teardown failed.'])
        self.assertEqual(self.log[-1], 'close')

    def test_cleanup_failure_does_not_replace_execution_failure(self):
        registry, events, log = Registry(), Events(), []
        class BrokenRobot(BaseRobot):
            def setup(self, ctx):
                raise ValueError('private')
        registry.register('test', BrokenRobot)
        class BrokenClose(FakeBrowser):
            def close(self):
                raise RuntimeError('private cleanup')
        result = Runner(registry, BrokenClose(log), None, events, Cancellation()).run('test', [], RunOptions())
        self.assertIsInstance(result.primary_error, ValueError)
        self.assertEqual(result.cleanup_errors, ['Browser or recording cleanup failed.'])

    def test_cancel_before_setup_still_releases_resources(self):
        registry, events, log, cancel = Registry(), Events(), [], Cancellation()
        cancel.cancel = True
        registry.register('test', BaseRobot)
        result = Runner(registry, FakeBrowser(log), None, events, cancel).run('test', [InputRow('1', {})], RunOptions())
        self.assertEqual(result.state, 'cancelled')
        self.assertEqual(result.unprocessed, ['1'])
        self.assertEqual(log, ['close'])

    def test_cancel_is_not_row_error(self):
        result = self.execute(self.robot(failure=ExecutionCancelled))
        self.assertEqual(result.state, 'cancelled')
        self.assertEqual(result.rows, [])
        self.assertEqual(result.unprocessed, ['1', '2'])
        self.assertEqual(self.log[-2:], ['teardown', 'close'])

    def test_checkpoint_between_actions(self):
        test = self
        class Robot(BaseRobot):
            def process(self, ctx, inputs):
                test.cancel.cancel = True
                ctx.click('must-not-click')
        self.assertEqual(self.execute(Robot).state, 'cancelled')
        self.assertNotIn('click', self.log)

    def test_invalid_registry_name_and_naming(self):
        self.assertEqual(robot_name('Invoice Checks'), 'ROBOT_INVOICE_CHECKS')
        with self.assertRaises(ValueError):
            Registry().resolve('arbitrary.module')

    def test_cleanup_after_browser_open_failure(self):
        registry, events, log = Registry(), Events(), []
        registry.register('test', BaseRobot)
        class Broken(FakeBrowser):
            def open(self, options):
                raise RuntimeError('private')
        result = Runner(registry, Broken(log), None, events, Cancellation()).run('test', [], RunOptions())
        self.assertEqual(result.state, 'failed')
        self.assertEqual(log, ['close'])
