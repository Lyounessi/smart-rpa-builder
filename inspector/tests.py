import asyncio
import io
import os
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import LiveServerTestCase, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from projects.models import Project, WorkflowStep
from .locators import safe_url, validate
from .models import ApplicationWindow, CaptureDraft, CapturedElement, InspectionCommand, InspectionSession
from .services import SERVER_INSTANCE, enqueue, finish_session, persist_draft, reconcile_sessions, save_draft, start_session


class InspectorTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.project = Project.objects.create(name='Suppliers')
        self.window = ApplicationWindow.objects.create(project=self.project, name='Portal', target_url='https://example.com')
        self.step = WorkflowStep.objects.create(project=self.project, window=self.window, position=1, name='Name', instruction='Fill name')
        self.session = InspectionSession.objects.create(project=self.project, window=self.window, step=self.step, server_instance=SERVER_INSTANCE, heartbeat=timezone.now(), status='browsing')

    def draft(self):
        return CaptureDraft.objects.get(pk=persist_draft(self.session.pk, {'tag':'input', 'name':'Supplier'},
            {'strategy':'label', 'value':'Supplier'}, {'status':'unique', 'count':1}, 'https://example.com/form',
            {'unit':'CSS pixels'}, b'example-masked-viewport', b'example-masked-crop'))

    def test_capture_is_only_attached_after_review_save(self):
        draft = self.draft()
        self.assertFalse(self.step.element_references.exists())
        element = save_draft(draft.pk, self.session, 'Supplier name', 'Input field')
        self.assertEqual(self.step.element_references.get().element, element)
        element.refresh_from_db()
        self.assertEqual(element.locator, draft.locator)
        self.assertTrue(Path(element.highlighted_screenshot.path).exists())
        self.assertEqual(element.highlighted_screenshot.name, draft.highlighted_screenshot.name)
        finish_session(self.session.pk)
        response = self.client.get(reverse('step-inspector', args=[self.project.pk, self.step.pk]))
        self.assertContains(response, 'Supplier name')
        self.assertContains(response, 'Open the inspection browser')

    def test_recapture_discards_unsaved_files_but_keeps_saved_target(self):
        saved = save_draft(self.draft().pk, self.session, 'Saved target', '')
        previous = self.draft()
        old_file = previous.highlighted_screenshot.path
        replacement = self.draft()
        self.assertFalse(Path(old_file).exists())
        self.assertFalse(CaptureDraft.objects.filter(pk=previous.pk).exists())
        self.assertTrue(Path(saved.highlighted_screenshot.path).exists())
        self.assertTrue(CaptureDraft.objects.filter(pk=replacement.pk).exists())
        self.assertEqual(self.step.element_references.get().element, saved)

    def test_changed_step_window_rejects_old_capture(self):
        draft = self.draft()
        self.step.window = ApplicationWindow.objects.create(project=self.project, name='Other', target_url='https://example.org')
        self.step.save()
        with self.assertRaises(ValidationError):
            save_draft(draft.pk, self.session, 'Old target', '')
        self.assertFalse(CapturedElement.objects.exists())

    @patch('inspector.services.subprocess.Popen')
    def test_only_one_browser_can_start(self, process):
        with self.assertRaises(ValidationError):
            start_session(self.step, 'http://127.0.0.1:8000')
        process.assert_not_called()
        finish_session(self.session.pk)
        new = start_session(self.step, 'http://127.0.0.1:8000')
        self.assertEqual(new.active_slot, 'local')
        process.assert_called_once()

    def test_dead_worker_and_server_restart_reconcile(self):
        self.session.heartbeat = timezone.now() - timedelta(minutes=2)
        self.session.save()
        reconcile_sessions()
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'interrupted')
        self.assertIsNone(self.session.active_slot)
        self.session.active_slot = 'local'
        self.session.server_instance = 'previous-process'
        self.session.heartbeat = timezone.now()
        self.session.save()
        reconcile_sessions()
        self.session.refresh_from_db()
        self.assertIsNone(self.session.active_slot)

    def test_commands_reject_foreign_elements_and_parallel_operations(self):
        other = ApplicationWindow.objects.create(project=self.project, name='Other', target_url='https://example.org')
        element = CapturedElement.objects.create(window=other, name='Other field', locator={'strategy':'label', 'value':'Other'})
        with self.assertRaises(ValidationError):
            enqueue(self.session, 'test', element)
        enqueue(self.session, 'select')
        with self.assertRaises(ValidationError):
            enqueue(self.session, 'select')
        enqueue(self.session, 'stop')
        finish_session(self.session.pk)
        self.assertFalse(InspectionCommand.objects.filter(status='pending').exists())

    def test_starting_session_can_be_stopped(self):
        self.session.status = 'starting'
        self.session.save()
        self.assertEqual(enqueue(self.session, 'stop').operation, 'stop')

    @patch('inspector.services.subprocess.Popen')
    def test_reuse_browser_keeps_draft_bound_to_original_step(self, process):
        draft = self.draft()
        next_step = WorkflowStep.objects.create(project=self.project, window=self.window, position=2, name='Next step', instruction='Click save')
        reused = start_session(next_step, 'http://127.0.0.1:8000')
        self.assertEqual(reused.pk, self.session.pk)
        process.assert_not_called()
        saved = save_draft(draft.pk, reused, 'Original step target', '')
        self.assertEqual(self.step.element_references.get().element, saved)
        self.assertFalse(next_step.element_references.exists())

    def test_review_routes_and_screenshots_are_step_scoped(self):
        draft = self.draft()
        image_url = reverse('inspector-screenshot', args=[self.project.pk, self.step.pk, 'draft', draft.pk, 'viewport'])
        response = self.client.get(image_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        response.close()
        other_step = WorkflowStep.objects.create(project=self.project, position=2, name='Other', instruction='Other')
        url = reverse('inspector-review', args=[self.project.pk, other_step.pk, draft.pk])
        self.assertEqual(self.client.post(url, {'name':'Wrong step', 'action':'save'}).status_code, 404)
        url = reverse('inspector-review', args=[self.project.pk, self.step.pk, draft.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'name':'Reviewed target', 'action':'save'}).status_code, 302)
        self.assertEqual(self.step.element_references.get().element.name, 'Reviewed target')
        self.assertEqual(self.client.get(image_url).status_code, 404)

    def test_discard_removes_draft_files(self):
        draft = self.draft()
        path = draft.element_screenshot.path
        self.client.post(reverse('inspector-review', args=[self.project.pk, self.step.pk, draft.pk]), {'action':'discard'})
        self.assertFalse(Path(path).exists())
        self.assertFalse(CaptureDraft.objects.exists())

    def test_live_health_only_accepts_current_server_session(self):
        url = reverse('inspector-health', args=[self.session.pk])
        self.assertEqual(self.client.get(url).json()['instance'], SERVER_INSTANCE)
        finish_session(self.session.pk)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_url_context_strips_sensitive_parts(self):
        self.assertEqual(safe_url('https://user:secret@example.com/form?token=secret#password'), 'https://example.com/form')
        self.assertEqual(safe_url('file:///secret'), '')


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'Set RUN_BROWSER_TESTS=1 and install Chromium to run browser checks.')
class BrowserCaptureTests(SimpleTestCase):
    def test_selection_masking_and_locator_results_in_chromium(self):
        asyncio.run(self.browser_check())

    async def browser_check(self):
        from PIL import Image
        from playwright.async_api import async_playwright
        from .management.commands.inspect_browser import capture
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width':900, 'height':600}, device_scale_factor=1)
            actions = []
            await page.expose_binding('__smartRpaAction', lambda source, value: actions.append(value['action']))
            await page.set_content('<label for="supplier">Supplier name</label><input id="supplier" value="SECRET-TEXT"><input type="password" value="SECRET-PASSWORD"><button onclick="document.body.dataset.submitted=1">Save supplier</button><button>Duplicate</button><button>Duplicate</button><input aria-label="Hidden" hidden><canvas id="drawing" width="60" height="30"></canvas>')
            await page.add_script_tag(path=str(Path(__file__).parent / 'selection.js'))
            await page.evaluate('() => window.__smartRpa.select()')
            await page.get_by_role('button', name='Save supplier', exact=True).click()
            self.assertEqual(actions, ['capture'])
            self.assertIsNone(await page.locator('body').get_attribute('data-submitted'))
            with patch('inspector.management.commands.inspect_browser.persist_draft') as persist:
                await capture(page, 'fake-session')
                arguments = persist.call_args.args
                self.assertEqual(arguments[2], {'strategy':'role', 'role':'button', 'name':'Save supplier'})
                self.assertNotIn('SECRET', str(arguments[1]))
                image = Image.open(io.BytesIO(arguments[6]))
                field = await page.locator('#supplier').bounding_box()
                self.assertEqual(image.getpixel((int(field['x']+5), int(field['y']+5)))[:3], (100,116,139))
                self.assertGreater(Image.open(io.BytesIO(arguments[7])).width, 0)
            self.assertEqual((await validate(page, {'strategy':'role', 'role':'button', 'name':'Duplicate'}))['status'], 'ambiguous')
            self.assertEqual((await validate(page, {'strategy':'label', 'value':'Absent'}))['status'], 'missing')
            self.assertEqual((await validate(page, {'strategy':'label', 'value':'Hidden'}))['status'], 'hidden')
            from .quality import fingerprint
            baseline = fingerprint(await page.evaluate('() => window.__smartRpa.metadata()'))
            definition = {'strategy':'role', 'role':'button', 'name':'Save supplier'}
            self.assertTrue((await validate(page, definition, baseline))['identity_matches'])
            wrong = dict(baseline, tag='a')
            self.assertEqual((await validate(page, definition, wrong))['status'], 'identity_mismatch')
            await page.evaluate('() => window.__smartRpa.select()')
            await page.locator('#supplier').click()
            with patch('inspector.management.commands.inspect_browser.persist_draft') as persist:
                await capture(page, 'fake-session')
                self.assertNotIn('SECRET', str(persist.call_args.args[1]))
                self.assertEqual(persist.call_args.args[2]['strategy'], 'role')
                highlighted = Image.open(io.BytesIO(persist.call_args.args[6]))
                field = await page.locator('#supplier').bounding_box()
                self.assertEqual(highlighted.getpixel((int(field['x']-2), int(field['y']+5)))[:3], (0,181,209))
            await page.evaluate('() => window.__smartRpa.select()')
            await page.get_by_role('button', name='Move toolbar', exact=True).click()
            await page.locator('#drawing').click()
            with self.assertRaises(Exception):
                await capture(page, 'fake-session')
            await browser.close()


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'Set RUN_BROWSER_TESTS=1 to run the visible browser lifecycle checks.')
class BrowserLifecycleTests(LiveServerTestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Lifecycle check')
        self.window = ApplicationWindow.objects.create(project=self.project, name='Test login', target_url=self.live_server_url + '/admin/login/')
        self.step = WorkflowStep.objects.create(project=self.project, window=self.window, position=1, name='Login field', instruction='Capture username')
        with patch('inspector.services.subprocess.Popen'):
            self.session = start_session(self.step, self.live_server_url)

    def run_worker(self):
        from .management.commands.inspect_browser import Command
        thread = threading.Thread(target=lambda: asyncio.run(Command().run_browser(str(self.session.pk), self.live_server_url)), daemon=True)
        thread.start()
        return thread

    def wait_status(self, expected, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.session.refresh_from_db()
            if self.session.status in expected:
                return self.session.status
            time.sleep(.1)
        self.fail(f'Worker did not reach {expected}; state was {self.session.status}: {self.session.message}')

    def test_visible_browser_stops_and_worker_exits(self):
        thread = self.run_worker()
        try:
            self.assertEqual(self.wait_status({'browsing', 'error'}), 'browsing')
            enqueue(self.session, 'select')
            self.assertEqual(self.wait_status({'selecting', 'error'}), 'selecting')
            enqueue(self.session, 'cancel')
            self.assertEqual(self.wait_status({'browsing', 'error'}), 'browsing')
            enqueue(self.session, 'stop')
            self.assertEqual(self.wait_status({'stopped', 'error'}), 'stopped')
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.session.refresh_from_db()
            self.assertIsNone(self.session.active_slot)
        finally:
            if thread.is_alive():
                InspectionCommand.objects.create(session=self.session, operation='stop')
                thread.join(10)

    def test_server_disconnect_closes_browser(self):
        with patch('inspector.management.commands.inspect_browser.server_alive', return_value=False):
            thread = self.run_worker()
            thread.join(20)
            self.assertFalse(thread.is_alive())
            self.session.refresh_from_db()
            self.assertEqual(self.session.status, 'interrupted')
            self.assertIsNone(self.session.active_slot)

    def test_capture_save_reload_and_test_after_browser_reopen(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            asyncio.run(self.capture_login_field())
            draft = CaptureDraft.objects.get(step=self.step, status='review')
            self.assertEqual(draft.selector_quality['assessment'], 'unverified')
            response = self.client.post(reverse('inspector-review', args=[self.project.pk, self.step.pk, draft.pk]),
                                        {'name':'Username field', 'description':'Captured login textbox', 'action':'save'})
            self.assertEqual(response.status_code, 302)
            finish_session(self.session.pk)
            self.assertContains(self.client.get(reverse('step-inspector', args=[self.project.pk, self.step.pk])), 'Username field')
            element = self.step.element_references.get().element
            self.assertEqual(element.selector_quality, draft.selector_quality)
            self.assertTrue(Path(element.highlighted_screenshot.path).exists())
            self.assertTrue(Path(element.element_screenshot.path).exists())
            asyncio.run(self.reopen_and_validate(element.locator))

    async def capture_login_field(self):
        from playwright.async_api import async_playwright
        from .management.commands.inspect_browser import capture
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width':1000, 'height':800})
            await page.expose_binding('__smartRpaAction', lambda source, value: None)
            await page.add_init_script(path=str(Path(__file__).parent / 'selection.js'))
            await page.goto(self.window.target_url)
            await page.evaluate('() => window.__smartRpa.select()')
            await page.get_by_label('Username:', exact=True).click()
            await capture(page, str(self.session.pk), self.step.pk)
            await browser.close()

    async def reopen_and_validate(self, locator):
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(self.window.target_url)
            self.assertEqual((await validate(page, locator))['status'], 'unique')
            await browser.close()
