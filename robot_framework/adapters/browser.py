from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time

from inspector.locators import resolve
from robot_framework.contracts import TechnicalError


class _BrowserSession:
    """Saved locator dictionaries and application URLs are injected, never queried here."""
    def __init__(self, elements, applications, artifact_dir):
        self.elements, self.applications = elements, applications
        self.artifact_dir = Path(artifact_dir)
        self.engine = self.browser = self.context = self.page = None
        self.popup_seen = False
        self.timeout = 10000

    def open(self, options):
        from playwright.sync_api import sync_playwright
        self.timeout = options.action_timeout_ms
        self.engine = sync_playwright().start()
        self.browser = self.engine.chromium.launch(headless=False)
        kwargs = {}
        if options.record_screen:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            kwargs['record_video_dir'] = str(self.artifact_dir)
        self.context = self.browser.new_context(**kwargs)
        self.context.set_default_timeout(self.timeout)
        self.context.set_default_navigation_timeout(self.timeout)
        self.page = self.context.new_page()
        self.context.on('page', self._popup)
        self.page.on('dialog', self._dialog)

    def _popup(self, page):
        self.popup_seen = True
        page.on('dialog', self._dialog)

    def _dialog(self, dialog):
        # Registering a listener prevents Playwright's automatic dismissal.
        self.popup_seen = True

    def _check(self):
        if self.popup_seen:
            raise TechnicalError('Unexpected popup or dialog requires review.')

    def _target(self, element_id):
        self._check()
        try:
            return resolve(self.page, self.elements[str(element_id)])
        except KeyError:
            raise TechnicalError('Unknown captured element.') from None

    def navigate(self, application_id):
        self._check()
        self.page.goto(self.applications[str(application_id)], wait_until='domcontentloaded')
        self._check()

    def fill(self, element_id, value):
        self._target(element_id).fill(str(value))
        self._check()

    def click(self, element_id):
        self._target(element_id).click()
        self._check()

    def select_option(self, element_id, value):
        self._target(element_id).select_option(str(value))
        self._check()

    def read_text(self, element_id):
        text = self._target(element_id).inner_text()
        self._check()
        return text

    def read_value(self, element_id):
        value = self._target(element_id).input_value()
        self._check()
        return value

    def wait_for_progress(self, element_id, previous_text, completion_element_id):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        deadline = time.monotonic() + self.timeout / 1000
        status, complete = self._target(element_id), self._target(completion_element_id)
        while time.monotonic() < deadline:
            self._check()
            if complete.count() > 1 or status.count() > 1:
                raise TechnicalError('Progress target is ambiguous.')
            if complete.count() == 1 and complete.is_visible():
                return
            if status.count() == 1 and status.is_visible():
                try:
                    value = status.inner_text(timeout=max(1,min(100,int((deadline-time.monotonic())*1000))))
                    if value.strip() and value != previous_text:
                        return
                except PlaywrightTimeout:
                    pass
            time.sleep(min(.05,max(0,deadline-time.monotonic())))
        raise PlaywrightTimeout('Progress condition did not change within the action timeout.')

    def assert_visible(self, element_id):
        self._target(element_id).wait_for(state='visible', timeout=self.timeout)
        self._check()

    def close(self):
        errors = []
        for resource in [self.context, self.browser, self.engine]:
            if resource:
                try:
                    resource.stop() if resource is self.engine else resource.close()
                except Exception:
                    errors.append(True)
        if errors:
            raise TechnicalError('Resource cleanup failed.')
        return [str(path) for path in self.artifact_dir.glob('*.webm')]


class PlaywrightBrowser:
    """Keep Playwright's event loop off the thread used by Django's synchronous ORM."""
    def __init__(self, elements, applications, artifact_dir):
        self.session = _BrowserSession(elements, applications, artifact_dir)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='robot-browser')

    def __getattr__(self, method):
        if method not in {'open', 'navigate', 'fill', 'click', 'select_option', 'read_text', 'read_value', 'wait_for_progress', 'assert_visible'}:
            raise AttributeError(method)
        def call(*args):
            return self.executor.submit(getattr(self.session, method), *args).result()
        return call

    def close(self):
        try:
            return self.executor.submit(self.session.close).result()
        finally:
            self.executor.shutdown(wait=True)
