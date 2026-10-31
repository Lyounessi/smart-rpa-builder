"""Opt-in visual checks use synthetic local records, never the live challenge."""
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from django.utils import timezone

from projects.models import Project,Dataset,DatasetRow
from .models import RobotRun,RowAttempt


@skipUnless(os.environ.get('RUN_BROWSER_TESTS')=='1','Opt-in results browser checks')
class ResultsBrowserTests(StaticLiveServerTestCase):
    def test_results_filters_links_and_mobile_layout(self):
        from playwright.sync_api import sync_playwright
        project=Project.objects.create(name='Supplier registration')
        dataset=Dataset.objects.create(project=project,name='Demo suppliers',source_name='fixture',headers=['name','email'],schema_snapshot=[],status='ready',row_count=1)
        stamp=timezone.now()
        run=RobotRun.objects.create(dataset=dataset,robot_name='ROBOT_FIXTURE',heartbeat=stamp,active_slot=None,
            state='completed',started_at=stamp,finished_at=stamp,outputs={'congrats':'All records processed successfully'})
        row=DatasetRow.objects.create(dataset=dataset,row_number=2,values={'name':'Alice Example','email':'alice@example.invalid'},processing_status='done')
        RowAttempt.objects.create(run=run,row=row,input_snapshot=row.values,outputs={'reference':'SUP-001'},outcome='OK',
            started_at=stamp,finished_at=stamp,business_completed_at=stamp)
        url=self.live_server_url+reverse('project-results',args=[project.pk])
        folder=Path(settings.MEDIA_ROOT)/'ui-preview'
        folder.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.goto(url)
                page.get_by_role('heading',name='Treated records and outcomes').wait_for()
                self.assertEqual(page.get_by_text('Alice Example',exact=True).count(),1)
                page.screenshot(path=str(folder/'refinement-results.png'),full_page=True)
                page.get_by_label('Status',exact=False).select_option('unconfirmed')
                page.get_by_role('button',name='Filter results').click()
                page.get_by_role('heading',name='No matching results').wait_for()
                page.get_by_role('link',name='Clear filters').click()
                page.get_by_text('Alice Example',exact=True).wait_for()
                page.set_viewport_size({'width':390,'height':844})
                self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                page.screenshot(path=str(folder/'refinement-results-mobile.png'),full_page=True)
                page.get_by_role('link',name='Pending inputs',exact=True).click()
                page.get_by_text('No pending or in-progress records.',exact=False).wait_for()
            finally:
                browser.close()
