from datetime import datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from projects.models import Project,Dataset,DatasetRow
from robot_framework.base import BaseRobot
from robot_framework.context import RobotContext
from robot_framework.contracts import RunOptions
from .adapters import create_run,DjangoQueue
from .models import RobotRun,RowAttempt,ProgressEvent


class ChallengeBrowser:
    """Local fixture: final Submit removes the form instead of starting another round."""
    def __init__(self):
        self.submitted=0
    def fill(self,element,value):
        pass
    def read_text(self,element):
        return 'Congratulations' if element=='complete' else f'Round {self.submitted+1}'
    def read_value(self,element):
        return ''
    def click(self,element):
        self.submitted+=1
    def assert_visible(self,element):
        if element=='field' and self.submitted==10:
            raise TimeoutError('The form has been replaced by the final result')
    def wait_for_progress(self,element,previous,completion):
        if self.submitted==10 or self.read_text(element)!=previous:
            return
        raise TimeoutError()


class ProjectResultsTests(TestCase):
    def setUp(self):
        self.project=Project.objects.create(name='Challenge results fixture')
        self.dataset=Dataset.objects.create(project=self.project,name='Ten records',status='ready',
            headers=['name'],schema_snapshot=[],row_count=10)
        self.rows=[DatasetRow.objects.create(dataset=self.dataset,row_number=i+2,values={'name':f'Record {i+1}'}) for i in range(10)]
        self.url=reverse('project-results',args=[self.project.pk])

    def execute(self,broken=False):
        run=create_run(self.dataset,'ROBOT_FIXTURE')
        queue=DjangoQueue(run)
        cancel=Mock()
        cancel.requested.return_value=False
        browser=ChallengeBrowser()
        class Robot(BaseRobot):
            def process(self,ctx,inputs):
                with ctx.step('submit'):
                    ctx.fill('field',inputs['name'])
                    previous=ctx.read_text('round')
                    ctx.click('submit')
                    if broken:
                        ctx.assert_visible('field')
                    else:
                        ctx.wait_for_progress('round',previous,'complete')
            def finalize(self,ctx):
                with ctx.step('final'):
                    ctx.extract_text('complete','congrats')
        result=Robot().execute(RobotContext(browser,None,queue,cancel),queue.rows(),RunOptions())
        queue.emit('run_completed' if result.state=='completed' else 'run_failed',summary=result)
        run.refresh_from_db()
        return run

    def test_ten_records_produce_ten_treatments_not_extra_submit_inputs(self):
        run=self.execute()
        self.assertEqual(run.counts,{'OK':10})
        self.assertEqual(run.outputs,{'congrats':'Congratulations'})
        self.assertEqual(self.dataset.rows.count(),10)
        self.assertEqual(self.dataset.rows.filter(processing_status='done').count(),10)
        self.assertEqual(run.attempts.filter(business_completed_at__isnull=False).count(),10)
        self.assertGreater(run.events.count(),10)
        page=self.client.get(self.url)
        self.assertEqual(page.context['page'].paginator.count,10)
        self.assertContains(page,'Congratulations')
        self.assertTrue(all(item.treatment_at for item in page.context['page']))
        queue=self.client.get(reverse('dataset-detail',args=[self.project.pk,self.dataset.pk]))
        self.assertEqual(queue.context['table'],[])
        self.assertEqual(queue.context['treated_count'],10)
        self.assertContains(queue,'Treated results')

    def test_final_submit_verification_failure_remains_pending_with_clear_evidence(self):
        run=self.execute(broken=True)
        self.assertEqual(run.counts,{'OK':9,'ERROR':1})
        self.assertEqual(self.dataset.rows.filter(processing_status='pending').count(),1)
        page=self.client.get(self.url,{'status':'unconfirmed'})
        self.assertEqual(page.context['page'].paginator.count,1)
        self.assertContains(page,'The click completed, but its subsequent success check failed')
        self.assertContains(page,'check the application before retrying')
        self.assertEqual(self.client.get(self.url).context['page'].paginator.count,9)
        pending=self.client.get(reverse('dataset-detail',args=[self.project.pk,self.dataset.pk]))
        self.assertEqual([row['number'] for row in pending.context['table']],[11])
        self.rows[-1].refresh_from_db()
        self.assertEqual(self.rows[-1].processing_status,'pending')
        self.assertContains(self.client.get(reverse('run-detail',args=[run.pk])),'subsequent success check failed')

    @override_settings(TIME_ZONE='Africa/Casablanca')
    def test_inclusive_treatment_dates_and_unconfirmed_attempts_are_separate(self):
        self.execute()
        zone=ZoneInfo('Africa/Casablanca')
        stamp=datetime(2026,10,31,0,15,tzinfo=zone)
        first=RowAttempt.objects.order_by('pk').first()
        RowAttempt.objects.exclude(pk=first.pk).update(business_completed_at=stamp-timedelta(days=1),finished_at=stamp-timedelta(days=1))
        RowAttempt.objects.filter(pk=first.pk).update(business_completed_at=stamp,finished_at=stamp)
        with timezone.override(zone):
            page=self.client.get(self.url,{'date_from':'2026-10-31','date_to':'2026-10-31'})
            self.assertEqual(page.context['page'].paginator.count,1)
            self.assertEqual(page.context['page'][0].pk,first.pk)
            self.assertEqual(self.client.get(self.url,{'date_from':'2026-11-01'}).context['page'].paginator.count,0)
        bad=self.client.get(self.url,{'date_from':'2026-11-01','date_to':'2026-10-31'})
        self.assertTrue(bad.context['form'].errors)
        self.assertEqual(bad.context['page'].paginator.count,0)

    def test_other_project_filters_and_records_are_not_exposed(self):
        self.execute()
        other=Project.objects.create(name='Other project')
        dataset=Dataset.objects.create(project=other,name='Other dataset',headers=[],schema_snapshot=[])
        run=RobotRun.objects.create(dataset=dataset,robot_name='OTHER',heartbeat=timezone.now())
        row=DatasetRow.objects.create(dataset=dataset,row_number=2,values={})
        RowAttempt.objects.create(run=run,row=row,outcome='OK',business_completed_at=timezone.now(),input_snapshot={'private':'OTHER_PROJECT_VALUE'})
        self.assertNotContains(self.client.get(self.url),'OTHER_PROJECT_VALUE')
        for params in [{'dataset':dataset.pk},{'run':str(run.pk)},{'version':'999'},{'date_from':'invalid'}]:
            page=self.client.get(self.url,params)
            self.assertTrue(page.context['form'].errors)
            self.assertEqual(page.context['page'].paginator.count,0)

    def test_history_uses_original_snapshot_not_current_values_and_preserves_deleted_rows(self):
        self.execute()
        row=self.rows[0]
        row.values={'name':'Edited later'}
        row.deleted_at=timezone.now()
        row.save()
        page=self.client.get(self.url)
        self.assertContains(page,'Record 1')
        self.assertNotContains(page,'Edited later')
        self.assertEqual(page.context['page'].paginator.count,10)

    def test_business_completion_is_preserved_even_if_later_notification_fails(self):
        self.execute()
        attempt=RowAttempt.objects.first()
        RowAttempt.objects.filter(pk=attempt.pk).update(outcome='ERROR',message='Notification failed after business completion')
        page=self.client.get(self.url)
        self.assertEqual(page.context['page'].paginator.count,10)
        self.assertEqual(self.client.get(self.url,{'status':'unconfirmed'}).context['page'].paginator.count,0)
        self.assertContains(page,'Outcome ERROR')
