from copy import deepcopy
from hashlib import sha256
from unittest.mock import patch
from unittest import skipUnless
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from projects.models import Project,Dataset,DatasetRow
from .demo import prepare_demo
from .models import RobotBuild,RobotRun,ProgressEvent,RowAttempt


class RunControlTests(TestCase):
    def setUp(self):
        self.project,self.dataset,self.session,self.build=prepare_demo(8766,local_robot=True)
        self.robot=self.build.robot
        self.url=reverse('robot-run',args=[self.robot.pk])

    def data(self,**kwargs):
        data={'build':self.build.pk,'dataset':self.dataset.pk,'row_limit':2,
            'reviewed_digest':self.build.source_digest,'acknowledged':'on'}
        data.update(kwargs)
        return data

    def version_two(self):
        build=RobotBuild.objects.get(pk=self.build.pk)
        build.pk=None
        build.version=2
        source=next(iter(build.source_files.values()))+'\n# Second reviewed version\n'
        build.source_files={self.robot.name+'.py':source}
        build.source_digest=sha256(source.encode()).hexdigest()
        build.save()
        return build

    def test_robot_button_and_free_modal_with_pending_counts(self):
        self.assertContains(self.client.get(reverse('robot-detail',args=[self.robot.pk])),'data-run-trigger')
        page=self.client.get(self.url,HTTP_HX_REQUEST='true')
        self.assertContains(page,'2 pending inputs')
        self.assertContains(page,'Review version 1 code')
        self.assertNotContains(page,'<!doctype html>')
        self.assertContains(self.client.get(self.url),'<!doctype html>')
        self.assertFalse(RobotRun.objects.exists())

    def test_version_selection_changes_digest_and_resets_acknowledgement(self):
        second=self.version_two()
        page=self.client.get(self.url,{'build':second.pk,'acknowledged':'on','reviewed_digest':self.build.source_digest},HTTP_HX_REQUEST='true')
        self.assertContains(page,second.source_digest)
        self.assertContains(page,'Review version 2 code')
        self.assertFalse(page.context['form'].initial.get('acknowledged',False))
        refreshed=self.client.post(self.url,self.data(build=second.pk,action='refresh'))
        self.assertEqual(refreshed.context['form'].initial['reviewed_digest'],second.source_digest)
        self.assertFalse(RobotRun.objects.exists())

    def test_dataset_pending_counts_and_schema_mismatch_are_explained(self):
        dataset=Dataset.objects.create(project=self.project,name='Old inputs',source_name='fixture',schema_snapshot=[],headers=['name'],status='ready',row_count=1)
        DatasetRow.objects.create(dataset=dataset,row_number=2,values={'name':'Alice'})
        page=self.client.get(self.url,{'dataset':dataset.pk})
        self.assertEqual(page.context['pending_count'],1)
        self.assertContains(page,'does not match the selected version')
        self.client.post(self.url,self.data(dataset=dataset.pk))
        self.assertFalse(RobotRun.objects.exists())
        dataset.schema_snapshot=[{'key':'name','data_type':'number','required':True}]
        dataset.save()
        self.assertContains(self.client.get(self.url,{'dataset':dataset.pk}),'does not match the selected version')
        self.client.post(self.url,self.data(dataset=dataset.pk))
        self.assertFalse(RobotRun.objects.exists())

    def test_valid_post_uses_selected_version_and_redirects_htmx_to_live_run(self):
        with patch('execution.draft_tests.launch_test') as launch:
            page=self.client.post(self.url,self.data(row_limit=50),HTTP_HX_REQUEST='true')
        run=RobotRun.objects.get()
        self.assertEqual(run.build_id,self.build.pk)
        self.assertEqual(run.test_options['planned_rows'],2)
        self.assertEqual(run.test_options['row_limit'],50)
        self.assertEqual(page.headers['HX-Redirect'],reverse('run-detail',args=[run.pk]))
        launch.assert_called_once()
        self.assertContains(self.client.get(reverse('robot-detail',args=[self.robot.pk])),'Open active execution')

    def test_inputs_added_after_queuing_do_not_expand_the_planned_count(self):
        from .adapters import DjangoQueue
        with patch('execution.draft_tests.launch_test'):
            self.client.post(self.url,self.data(row_limit=5))
        run=RobotRun.objects.get()
        DatasetRow.objects.create(dataset=self.dataset,row_number=4,values={'name':'Charlie'})
        self.assertEqual(run.test_options['planned_rows'],2)
        self.assertEqual(len(DjangoQueue(run).rows()),2)

    def test_missing_review_stale_digest_limits_and_foreign_choices_are_rejected(self):
        other=Project.objects.create(name='Other')
        dataset=Dataset.objects.create(project=other,name='Other',source_name='fixture',schema_snapshot=[],headers=[],status='ready')
        for changes in [{'acknowledged':''},{'reviewed_digest':'old'},{'row_limit':51},{'dataset':dataset.pk}]:
            with patch('execution.draft_tests.launch_test') as launch:
                page=self.client.post(self.url,self.data(**changes),HTTP_HX_REQUEST='true')
            self.assertEqual(page.status_code,200)
            self.assertNotIn('HX-Redirect',page.headers)
            launch.assert_not_called()
            self.assertFalse(RobotRun.objects.exists())
        self.assertEqual(self.client.get(self.url,{'dataset':dataset.pk}).status_code,404)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url,self.data()).status_code,403)

    def test_changed_version_digest_and_no_pending_inputs_block_start(self):
        second=self.version_two()
        self.client.post(self.url,self.data(build=second.pk))
        self.assertFalse(RobotRun.objects.exists())
        self.dataset.rows.update(deleted_at=timezone.now())
        self.assertContains(self.client.get(self.url),'No confirmed dataset has valid pending inputs')
        self.assertContains(self.client.get(reverse('robot-detail',args=[self.robot.pk])),'No pending inputs')

    def test_stale_context_is_explained_without_queuing(self):
        self.project.automation_goal='Changed after generation'
        self.project.save()
        self.assertContains(self.client.get(self.url),'current specification and valid source')
        self.client.post(self.url,self.data())
        self.assertFalse(RobotRun.objects.exists())

    def test_live_progress_counts_and_stop_are_immediate_and_finished_run_stops_polling(self):
        with patch('execution.draft_tests.launch_test'):
            self.client.post(self.url,self.data())
        run=RobotRun.objects.get()
        run.state='running'
        run.started_at=timezone.now()
        run.save()
        row=self.dataset.rows.first()
        RowAttempt.objects.create(run=run,row=row,outcome='OK',input_snapshot=deepcopy(row.values))
        ProgressEvent.objects.create(run=run,kind='step_started',step='save_greeting')
        page=self.client.get(reverse('run-detail',args=[run.pk]))
        self.assertContains(page,'save_greeting')
        self.assertContains(page,'Stop execution')
        self.assertEqual(page.context['live_counts']['OK'],1)
        self.assertEqual(page.context['processed_count'],1)
        stopped=self.client.post(reverse('run-cancel',args=[run.pk]),HTTP_HX_REQUEST='true')
        self.assertContains(stopped,'Stopping…')
        self.assertNotContains(stopped,'<!doctype html>')
        run.refresh_from_db()
        self.assertTrue(run.cancel_requested)
        run.state='cancelled'
        run.active_slot=None
        run.finished_at=timezone.now()
        run.save()
        page=self.client.get(reverse('run-detail',args=[run.pk]),HTTP_HX_REQUEST='true')
        self.assertContains(page,'Stopped')
        self.assertContains(page,'View outputs and statistics')
        self.assertNotContains(page,'hx-trigger="every 2s"')


@skipUnless(os.environ.get('RUN_BROWSER_TESTS')=='1','Opt-in run-dialog browser check')
class RunControlBrowserTests(StaticLiveServerTestCase):
    def test_dialog_keyboard_version_review_and_live_stop_flow(self):
        from playwright.sync_api import sync_playwright,expect
        project,dataset,session,build=prepare_demo(8766,local_robot=True)
        second=RobotBuild.objects.get(pk=build.pk)
        second.pk=None
        second.version=2
        source=next(iter(second.source_files.values()))+'\n# UI version review fixture\n'
        second.source_files={build.robot.name+'.py':source}
        second.source_digest=sha256(source.encode()).hexdigest()
        second.save()
        artifacts=Path(settings.MEDIA_ROOT)/'ui-preview'
        artifacts.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':1280,'height':1000})
                errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(self.live_server_url+reverse('robot-detail',args=[build.robot_id]))
                page.screenshot(path=str(artifacts/'run-button.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(artifacts/'run-button-mobile.png'),full_page=True)
                page.set_viewport_size({'width':1280,'height':1000})
                page.get_by_role('link',name='Run robot',exact=True).click()
                dialog=page.locator('#robot-run-dialog')
                expect(dialog).to_be_visible()
                expect(page.locator('#id_build')).to_have_value(str(second.pk))
                page.locator('#id_acknowledged').check()
                page.locator('#id_build').select_option(str(build.pk))
                expect(page.locator('#id_reviewed_digest')).to_have_value(build.source_digest)
                expect(page.locator('#id_acknowledged')).not_to_be_checked()
                page.screenshot(path=str(artifacts/'run-dialog.png'))
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(artifacts/'run-dialog-mobile.png'))
                self.assertTrue(page.locator('#robot-run-dialog').evaluate('(element) => element.scrollWidth <= element.clientWidth'))
                page.set_viewport_size({'width':1280,'height':1000})
                page.keyboard.press('Escape')
                expect(dialog).not_to_be_visible()
                page.get_by_role('link',name='Run robot',exact=True).click()
                expect(dialog).to_be_visible()
                expect(page.locator('#id_reviewed_digest')).to_have_value(second.source_digest)
                page.get_by_text('Review version 2 code',exact=True).click()
                expect(page.locator('.source-review pre')).to_contain_text('ROBOT_GREETING_DRAFT_DEMO')
                page.get_by_text('Review version 2 code',exact=True).click()
                page.locator('#id_acknowledged').check()
                with patch('execution.draft_tests.launch_test') as launch:
                    page.get_by_role('button',name='Start robot',exact=True).click()
                    page.wait_for_url('**/execution/**/')
                    launch.assert_called_once()
                # Playwright's sync bridge has an event loop on this thread;
                # keep ORM reads on a separate thread, as the worker does.
                with ThreadPoolExecutor(max_workers=1) as database:
                    run=database.submit(lambda:RobotRun.objects.values('pk','build_id').get()).result()
                self.assertEqual(run['build_id'],second.pk)
                page.get_by_role('button',name='Stop execution',exact=True).click()
                expect(page.get_by_role('button',name='Stopping…',exact=True)).to_be_disabled()
                with ThreadPoolExecutor(max_workers=1) as database:
                    cancelled=database.submit(lambda:RobotRun.objects.get(pk=run['pk']).cancel_requested).result()
                self.assertTrue(cancelled)
                self.assertEqual(errors,[])
                page.screenshot(path=str(artifacts/'run-stopping.png'),full_page=True)
            finally:
                browser.close()
