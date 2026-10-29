import os
from threading import Thread
from http.server import ThreadingHTTPServer
from unittest import skipUnless
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from django.core.management import call_command

from .demo import prepare_demo, GreetingHandler
from .draft_tests import queue_test, execute_test
from .models import RobotRun
from projects.models import Project, Dataset


class GreetingBrowser:
    def __init__(self,*args):
        self.name = ''
    def open(self,options): pass
    def close(self): return []
    def navigate(self,application_id): self.name = ''
    def fill(self,element_id,value): self.name = value
    def click(self,element_id): pass
    def assert_visible(self,element_id): pass
    def read_text(self,element_id): return 'Hello, '+self.name+'!'


class DraftTestTests(TestCase):
    def setUp(self):
        self.project,self.dataset,self.session,self.build = prepare_demo(8766,local_robot=True)

    def queue(self,**kwargs):
        return queue_test(self.build,self.dataset,reviewed_digest=self.build.source_digest,acknowledged=True,**kwargs)

    def test_get_is_free_and_post_requires_source_review_csrf_and_project_dataset(self):
        url = reverse('robot-build-test',args=[self.build.robot_id,self.build.version])
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code,403)
        self.assertContains(self.client.get(reverse('robot-build-detail',args=[self.build.robot_id,1])), 'Run reviewed draft test')
        with patch('execution.draft_tests.launch_test') as launch:
            response = self.client.post(url,{'dataset':self.dataset.pk,'row_limit':1,'reviewed_digest':self.build.source_digest})
            self.assertEqual(response.status_code,200)
            launch.assert_not_called()
            self.assertFalse(RobotRun.objects.exists())
            other = Project.objects.create(name='Other')
            dataset = Dataset.objects.create(project=other,name='Other',source_name='other',schema_snapshot=[],headers=[],status='ready')
            self.client.post(url,{'dataset':dataset.pk,'row_limit':1,'reviewed_digest':self.build.source_digest,'acknowledged':'on'})
            launch.assert_not_called()
            response = self.client.post(url,{'dataset':self.dataset.pk,'row_limit':1,'reviewed_digest':self.build.source_digest,'acknowledged':'on'})
            self.assertEqual(response.status_code,302)
            launch.assert_called_once()

    def test_review_fingerprint_stale_context_and_limits_block_before_import(self):
        with self.assertRaises(ValueError):
            queue_test(self.build,self.dataset,reviewed_digest=self.build.source_digest,acknowledged=False)
        with self.assertRaises(ValueError):
            queue_test(self.build,self.dataset,reviewed_digest='wrong',acknowledged=True)
        for limit in (0,6,True):
            with self.assertRaises(ValueError): self.queue(row_limit=limit)
        self.project.automation_goal='Changed'
        self.project.save()
        with self.assertRaises(ValueError): self.queue()
        self.assertFalse(RobotRun.objects.exists())

    def test_selected_build_runs_limited_rows_once_and_preserves_draft(self):
        run = self.queue(row_limit=1)
        execute_test(run.pk,browser_factory=GreetingBrowser)
        execute_test(run.pk,browser_factory=lambda *args: self.fail('Duplicate worker opened browser'))
        run.refresh_from_db()
        self.assertEqual(run.state,'completed')
        self.assertEqual(run.counts,{'OK':1})
        self.assertEqual(run.build_id,self.build.pk)
        self.assertEqual(run.attempts.get().outputs,{'greeting':'Hello, Alice!'})
        self.assertEqual(self.dataset.rows.filter(processing_status='done').count(),1)
        self.assertEqual(self.dataset.rows.filter(processing_status='pending').count(),1)
        self.build.refresh_from_db()
        self.assertTrue(self.build.is_draft)
        self.assertEqual(self.build.status,'validated')
        self.assertIsNotNone(run.source_reviewed_at)
        self.assertEqual(run.reviewed_source_digest,self.build.source_digest)
        self.assertIsNone(run.active_slot)

    def test_source_changed_or_cancelled_before_worker_never_opens_browser(self):
        run=self.queue()
        self.build.source_files={self.build.robot.name+'.py':'print("changed")'}
        self.build.save()
        execute_test(run.pk,browser_factory=lambda *args: self.fail('Tampered source opened browser'))
        run.refresh_from_db()
        self.assertEqual(run.state,'failed')
        self.assertFalse(run.attempts.exists())
        self.assertEqual(self.dataset.rows.filter(processing_status='pending').count(),2)

    def test_cancellation_before_import_preserves_pending_rows(self):
        run=self.queue()
        run.cancel_requested=True
        run.save()
        execute_test(run.pk,browser_factory=lambda *args:self.fail('Cancelled test opened browser'))
        run.refresh_from_db()
        self.assertEqual(run.state,'cancelled')
        self.assertFalse(run.attempts.exists())

    def test_launch_failure_releases_slot_without_claiming_rows(self):
        from .draft_tests import launch_test
        run=self.queue()
        with patch('execution.draft_tests.subprocess.Popen',side_effect=OSError):
            launch_test(run)
        run.refresh_from_db()
        self.assertEqual(run.state,'failed')
        self.assertIsNone(run.active_slot)
        self.assertFalse(run.attempts.exists())


@skipUnless(os.environ.get('RUN_BROWSER_TESTS')=='1','Opt-in real Chromium draft test')
class DraftBrowserTests(TransactionTestCase):
    def test_reviewed_draft_two_real_browser_rows_and_saved_outputs(self):
        with ThreadingHTTPServer(('127.0.0.1',0),GreetingHandler) as server:
            thread=Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                project,dataset,session,build=prepare_demo(server.server_port,local_robot=True)
                call_command('test_robot_build',build.pk,dataset=dataset.pk,reviewed_source_digest=build.source_digest)
                run=RobotRun.objects.get(build=build)
                self.assertEqual(run.state,'completed',run.message)
                self.assertEqual(run.counts,{'OK':2})
                self.assertEqual(list(run.attempts.order_by('row__row_number').values_list('outputs',flat=True)),
                    [{'greeting':'Hello, Alice!'},{'greeting':'Hello, Bob!'}])
                self.assertEqual(dataset.rows.filter(processing_status='done').count(),2)
                self.assertIsNotNone(run.finished_at)
                self.assertIsNone(run.active_slot)
                self.assertContains(self.client.get(reverse('robot-detail',args=[build.robot_id])), 'Hello, Alice!')
            finally:
                server.shutdown()
                thread.join(timeout=3)
