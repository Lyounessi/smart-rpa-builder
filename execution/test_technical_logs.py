import json
from types import SimpleNamespace
from unittest.mock import Mock
from unittest import skipUnless
import os

from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from projects.models import Project, Dataset
from robot_framework.context import RobotContext
from .models import RobotRun, ProgressEvent
from .adapters import DjangoQueue


class DiagnosticTests(SimpleTestCase):
    def test_action_failure_keeps_code_locations_but_excludes_values_and_exception_text(self):
        events = Mock()
        browser = Mock()
        browser.fill.side_effect = RuntimeError('PRIVATE_PASSWORD')
        ctx = RobotContext(browser, None, events, SimpleNamespace(requested=lambda:False))
        with self.assertRaises(RuntimeError), ctx.step('fill_name'):
            ctx.fill('captured-target', 'PRIVATE_INPUT')
        calls = events.emit.call_args_list
        self.assertEqual([call.args[0] for call in calls],
            ['step_started','action_started','action_failed','step_failed'])
        diagnostic = calls[2].kwargs['diagnostic']
        self.assertEqual(diagnostic['exception_type'], 'RuntimeError')
        self.assertEqual(diagnostic['target'], 'captured-target')
        self.assertIn('duration_ms', diagnostic)
        self.assertTrue(diagnostic['frames'])
        self.assertNotIn('PRIVATE_', str(calls))


class TechnicalLogViewsTests(TestCase):
    def test_persist_and_download_run_diagnostics(self):
        project = Project.objects.create(name='Logs fixture')
        dataset = Dataset.objects.create(project=project,name='Inputs',headers=[],schema_snapshot=[])
        run = RobotRun.objects.create(dataset=dataset,robot_name='ROBOT_LOGS',heartbeat=timezone.now())
        DjangoQueue(run).emit('action_failed',step='fill_name',diagnostic={
            'action':'fill','target':'fixture-target','exception_type':'TimeoutError','duration_ms':1000})
        response = self.client.get(reverse('run-logs',args=[run.pk]))
        self.assertEqual(response.status_code,200)
        payload = json.loads(b''.join(response.streaming_content))
        self.assertEqual(payload['diagnostic']['exception_type'],'TimeoutError')
        self.assertEqual(payload['step'],'fill_name')
        page = self.client.get(reverse('run-detail',args=[run.pk]))
        self.assertContains(page,'Technical execution logs')
        self.assertContains(page,'TimeoutError')
        self.assertEqual(ProgressEvent.objects.filter(run=run).count(),1)


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1','Opt-in bounded progress browser test')
class BrowserProgressTests(SimpleTestCase):
    def test_changed_round_or_final_completion_and_real_input_values(self):
        from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
        from robot_framework.adapters.browser import _BrowserSession
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content('<button id="round">Round 1</button><div id="done" hidden>Congratulations</div><input id="name" value="Alice">')
                session = _BrowserSession({'round':{'strategy':'css','value':'#round'},
                    'done':{'strategy':'css','value':'#done'},'name':{'strategy':'css','value':'#name'}},{},'.')
                session.page,session.timeout = page,100
                self.assertEqual(session.read_value('name'),'Alice')
                with self.assertRaises(BrowserTimeout):
                    session.wait_for_progress('round','Round 1','done')
                page.locator('#round').evaluate('(el) => el.textContent="Round 2"')
                session.wait_for_progress('round','Round 1','done')
                page.locator('#round').evaluate('(el) => el.remove()')
                page.locator('#done').evaluate('(el) => el.hidden=false')
                session.wait_for_progress('round','Round 2','done')
            finally:
                browser.close()
