from contextlib import contextmanager

from .contracts import ExecutionCancelled, Progress


class RobotContext:
    def __init__(self, browser, secrets, events, cancellation):
        self.browser = browser
        self.secrets = secrets
        self.events = events
        self.cancellation = cancellation
        self.row = None
        self.failed_step = None
        self.cleaning = False

    def emit(self, kind, **data):
        event = Progress(kind, row=self.row, **data)
        self.events.emit(event.kind, row=event.row, step=event.step, result=event.result, summary=event.summary)

    def checkpoint(self):
        if not self.cleaning and self.cancellation.requested():
            raise ExecutionCancelled()

    @contextmanager
    def step(self, step_id):
        self.checkpoint()
        self.emit('step_started', step=str(step_id))
        try:
            yield
        except BaseException:
            self.failed_step = str(step_id)
            self.emit('step_failed', step=str(step_id))
            raise
        else:
            self.emit('step_completed', step=str(step_id))

    def _action(self, method, *args):
        self.checkpoint()
        return getattr(self.browser, method)(*args)

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

    def assert_visible(self, element_id):
        return self._action('assert_visible', element_id)
