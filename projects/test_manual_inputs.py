from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from execution.adapters import DjangoQueue, create_run
from execution.models import Robot
from robot_framework.contracts import RowResult, Outcome, RunResult, RunState
from .models import Project, ProjectInput, Dataset, DatasetRow
from .manual_inputs import save_input, row_revision


class ManualInputTests(TestCase):
    def setUp(self):
        self.project=Project.objects.create(name='Manual inputs')
        ProjectInput.objects.create(project=self.project,key='name')
        self.number=ProjectInput.objects.create(project=self.project,key='amount',data_type='number',required=False)
        self.schema=list(self.project.inputs.values('key','description','data_type','required'))
        self.dataset=Dataset.objects.create(project=self.project,name='Inputs',source_name='fixture',
            schema_snapshot=self.schema,headers=['name','amount'],status='ready',row_count=1)
        self.row=DatasetRow.objects.create(dataset=self.dataset,row_number=2,values={'name':'Alice','amount':'1.20'})

    def url(self,name,row=None,project=None):
        args=[(project or self.project).pk,self.dataset.pk]
        if row is not None: args.append(row.pk)
        return reverse(name,args=args)

    def data(self,name='Bob',amount='2.50',row=None):
        return {'value_name':name,'value_amount':amount,'revision':row_revision(row) if row else ''}

    def test_create_manual_dataset_add_and_confirm(self):
        url=reverse('dataset-create',args=[self.project.pk])
        self.assertContains(self.client.get(reverse('project-detail',args=[self.project.pk])),'Create dataset manually')
        before=Dataset.objects.count()
        self.client.get(url)
        self.assertEqual(Dataset.objects.count(),before)
        response=self.client.post(url,{'name':'Typed inputs'})
        dataset=Dataset.objects.get(name='Typed inputs')
        self.assertEqual(response.status_code,302)
        self.assertEqual(dataset.schema_snapshot,self.schema)
        self.assertEqual(dataset.status,'preview')
        self.client.post(reverse('dataset-confirm',args=[self.project.pk,dataset.pk]))
        dataset.refresh_from_db()
        self.assertEqual(dataset.status,'preview')
        response=self.client.post(reverse('dataset-row-create',args=[self.project.pk,dataset.pk]),self.data())
        self.assertEqual(response.status_code,302)
        dataset.refresh_from_db()
        self.assertEqual(dataset.row_count,1)
        self.assertEqual(dataset.invalid_row_count,0)
        self.assertEqual(dataset.rows.get().processing_status,'pending')
        self.client.post(reverse('dataset-confirm',args=[self.project.pk,dataset.pk]))
        dataset.refresh_from_db()
        self.assertEqual(dataset.status,'ready')

    def test_validation_numbers_required_length_and_saved_schema(self):
        url=self.url('dataset-row-create')
        for name,amount in [('', '1'),('Bob','NaN'),('Bob','1e101'),('Bob','x'),('x'*2001,'1')]:
            self.assertEqual(self.client.post(url,self.data(name,amount)).status_code,200)
        self.assertEqual(self.dataset.rows.count(),1)
        self.number.key='different'
        self.number.data_type='text'
        self.number.save()
        self.assertContains(self.client.get(url),'value_amount')
        self.assertEqual(self.client.post(url,self.data(amount='001.20')).status_code,302)
        row=self.dataset.rows.order_by('-row_number').first()
        self.assertEqual(row.values,{'name':'Bob','amount':'1.20'})
        self.assertEqual(row.row_number,3)
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status,'ready')
        self.assertEqual(self.dataset.row_count,2)

    def test_pending_edit_optimistic_revision_and_locked_states(self):
        url=self.url('dataset-row-edit',self.row)
        stale=self.data(row=self.row)
        self.assertEqual(self.client.post(url,stale).status_code,302)
        self.assertContains(self.client.post(url,stale),'changed since you opened')
        for state in ('in_progress','done'):
            self.row.refresh_from_db()
            self.row.processing_status=state
            self.row.save()
            self.assertContains(self.client.post(url,self.data('Changed',row=self.row)),'locked')
            self.row.refresh_from_db()
            self.assertEqual(self.row.values['name'],'Bob')

    def test_invalid_preview_row_can_be_repaired_and_counts_refreshed(self):
        self.dataset.status='preview'
        self.dataset.invalid_row_count=1
        self.dataset.save()
        self.row.errors=['name: required value is missing.']
        self.row.values={'name':'','amount':''}
        self.row.save()
        response=self.client.post(self.url('dataset-row-edit',self.row),self.data(row=self.row))
        self.assertEqual(response.status_code,302)
        self.dataset.refresh_from_db()
        self.row.refresh_from_db()
        self.assertEqual(self.row.errors,[])
        self.assertEqual(self.dataset.invalid_row_count,0)
        self.assertEqual(self.dataset.status,'preview')

    def test_done_duplicate_preserves_original_and_requires_post(self):
        self.row.processing_status='done'
        self.row.save()
        url=self.url('dataset-row-duplicate',self.row)
        self.client.get(url)
        self.assertEqual(self.dataset.rows.count(),1)
        self.assertEqual(self.client.post(url,self.data('Charlie',row=self.row)).status_code,302)
        self.row.refresh_from_db()
        self.assertEqual(self.row.values['name'],'Alice')
        duplicate=self.dataset.rows.exclude(pk=self.row.pk).get()
        self.assertEqual(duplicate.values['name'],'Charlie')
        self.assertEqual(duplicate.processing_status,'pending')
        self.assertFalse(duplicate.rowattempt_set.exists())
        self.assertEqual(Client(enforce_csrf_checks=True).post(url,self.data(row=self.row)).status_code,403)

    def test_scoping_claim_lock_and_capacity(self):
        other=Project.objects.create(name='Other')
        self.assertEqual(self.client.get(reverse('dataset-row-edit',args=[self.project.pk,self.dataset.pk,0])).status_code,404)
        for route in ('dataset-row-edit','dataset-row-duplicate'):
            self.assertEqual(self.client.get(self.url(route,self.row,other)).status_code,404)
        run=create_run(self.dataset,'ROBOT_MANUAL_INPUTS')
        self.row.claimed_by=run
        self.row.save()
        with self.assertRaises(ValidationError):
            save_input(self.dataset,{'name':'X','amount':''},row_id=self.row.pk,expected_revision=row_revision(self.row))
        with patch('projects.manual_inputs.MAX_ROWS',1):
            with self.assertRaises(ValidationError):
                save_input(self.dataset,{'name':'X','amount':''})

    def test_claim_refreshes_queued_values_and_failed_history_keeps_exact_inputs(self):
        robot=Robot.objects.create(project=self.project,name='ROBOT_MANUAL_INPUTS')
        run=create_run(self.dataset,robot.name)
        queue=DjangoQueue(run)
        selected=queue.rows()
        self.assertEqual(selected[0].values['name'],'Alice')
        save_input(self.dataset,{'name':'Before claim','amount':'2'},row_id=self.row.pk,expected_revision=row_revision(self.row))
        queue.emit('run_started')
        queue.emit('row_started',row=str(self.row.pk))
        self.assertEqual(selected[0].values['name'],'Before claim')
        attempt=run.attempts.get()
        self.assertEqual(attempt.input_snapshot,{'name':'Before claim','amount':'2'})
        self.row.refresh_from_db()
        with self.assertRaises(ValidationError):
            save_input(self.dataset,{'name':'Locked','amount':''},row_id=self.row.pk,expected_revision=row_revision(self.row))
        result=RowResult(str(self.row.pk),Outcome.ERROR)
        queue.emit('row_finished',row=str(self.row.pk),result=result)
        queue.emit('run_completed',summary=RunResult(state=RunState.COMPLETED,rows=[result]))
        self.row.refresh_from_db()
        save_input(self.dataset,{'name':'After failure','amount':'3'},row_id=self.row.pk,expected_revision=row_revision(self.row))
        attempt.refresh_from_db()
        self.assertEqual(attempt.input_snapshot['name'],'Before claim')
        page=self.client.get(reverse('robot-detail',args=[robot.pk]))
        self.assertContains(page,'Before claim')
        self.assertNotContains(page,'After failure')

    def test_no_input_definitions_cannot_create_manual_dataset(self):
        project=Project.objects.create(name='Empty')
        self.assertContains(self.client.post(reverse('dataset-create',args=[project.pk]),{'name':'No fields'}),'Define between 1 and 30')
        self.assertFalse(project.datasets.exists())
