from contextlib import contextmanager
import re
import time
import traceback
from pathlib import Path

from .contracts import ExecutionCancelled, Progress, RowResult, Outcome
from .email import EmailService, UnconfiguredEmail


class RobotContext:
    def __init__(self, browser, secrets, events, cancellation, email=None, email_timeout_seconds=15):
        self.browser = browser
        self.secrets = secrets
        self.events = events
        self.cancellation = cancellation
        self.row = None
        self.failed_step = None
        self.cleaning = False
        self.active_step = None
        self.business_succeeded = False
        self.outputs = {}
        self.finalizing = False
        self.email = EmailService(self, email if email is not None else UnconfiguredEmail(), email_timeout_seconds)

    def emit(self, kind, **data):
        event = Progress(kind, row=self.row, **data)
        extra = {'action_status': event.action_status} if event.action_status is not None else {}
        if event.diagnostic is not None:
            extra['diagnostic'] = event.diagnostic
        self.events.emit(event.kind, row=event.row, step=event.step, result=event.result, summary=event.summary, **extra)

    def business_completed(self):
        """Persist verified business success before attempting optional notifications."""
        if self.row is None or self.cleaning:
            raise ValueError('Business completion requires an active input row.')
        if not self.business_succeeded:
            self.emit('business_completed', step=self.active_step,
                result=RowResult(str(self.row), Outcome.OK, outputs=dict(self.outputs)))
            self.business_succeeded = True

    def checkpoint(self):
        if not self.cleaning and self.cancellation.requested():
            raise ExecutionCancelled()

    @contextmanager
    def step(self, step_id):
        self.checkpoint()
        previous_step, self.active_step = self.active_step, str(step_id)
        self.emit('step_started', step=str(step_id))
        try:
            yield
        except BaseException as error:
            self.failed_step = str(step_id)
            self.emit('step_failed', step=str(step_id), diagnostic=self._failure(error))
            raise
        else:
            self.emit('step_completed', step=str(step_id))
        finally:
            self.active_step = previous_step

    def _action(self, method, *args):
        self.checkpoint()
        diagnostic = {'action':method, 'target':str(args[0])[:200] if args else ''}
        started = time.monotonic()
        self.emit('action_started', step=self.active_step, diagnostic=diagnostic)
        try:
            value = getattr(self.browser, method)(*args)
        except BaseException as error:
            self.emit('action_failed', step=self.active_step, diagnostic={**diagnostic,
                'duration_ms':round((time.monotonic()-started)*1000), **self._failure(error)})
            raise
        self.emit('action_completed', step=self.active_step, diagnostic={**diagnostic,
            'duration_ms':round((time.monotonic()-started)*1000)})
        return value

    @staticmethod
    def _failure(error):
        # No exception messages, source lines or local variables: browser errors can include values.
        frames = traceback.extract_tb(error.__traceback__)
        frames = frames if len(frames) <= 12 else frames[:6] + frames[-6:]
        return {'exception_type':type(error).__name__, 'frames':[
            {'file':Path(frame.filename).name, 'line':frame.lineno, 'function':frame.name}
            for frame in frames]}

    def navigate(self, application_id):
        return self._action('navigate', application_id)

    def fill(self, element_id, value):
        return self._action('fill', element_id, value)

    def click(self, element_id):
        return self._action('click', element_id)

    def select_option(self, element_id, value):
        return self._action('select_option', element_id, value)

    def read_text(self, element_id):
        return self._action('read_text', element_id)

    def read_value(self, element_id):
        return self._action('read_value', element_id)

    def wait_for_progress(self, element_id, previous_text, completion_element_id):
        """Wait for a changed visible status or the final completion target."""
        return self._action('wait_for_progress', element_id, previous_text, completion_element_id)

    def extract_text(self, element_id, output_key):
        """Read captured text into the current row's named results, without changing inputs."""
        if (self.row is None and not self.finalizing) or self.cleaning or (self.business_succeeded and not self.finalizing):
            raise ValueError('Extraction requires an active row before business completion.')
        if not isinstance(output_key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', output_key):
            raise ValueError('Invalid output name.')
        if output_key in self.outputs:
            raise ValueError('An output may only be extracted once per row.')
        value = self.read_text(element_id)
        if not isinstance(value, str) or len(value.encode('utf-8')) > 16384:
            raise ValueError('Extracted text must be at most 16 KB.')
        if sum(len(item.encode('utf-8')) for item in self.outputs.values()) + len(value.encode('utf-8')) > 65536:
            raise ValueError('Row outputs exceed 64 KB.')
        self.outputs[output_key] = value
        return value

    def assert_visible(self, element_id):
        return self._action('assert_visible', element_id)
