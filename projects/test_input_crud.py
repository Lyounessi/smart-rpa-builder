from django.test import TestCase, Client
from django.urls import reverse

from execution.adapters import create_run, DjangoQueue
from execution.models import Robot
from robot_framework.contracts import RowResult, RunResult, RunState, Outcome
from .models import Project, ProjectInput, WorkflowStep, Dataset, DatasetRow
from .manual_inputs import row_revision, definition_revision, save_input


class InputCRUDTests(TestCase):
    def setUp(self):
        self.project=Project.objects.create(name='Input CRUD')
        self.definition=ProjectInput.objects.create(project=self.project,key='name')
        self.schema=list(self.project.inputs.values('key','description','data_type','required'))
        self.dataset=Dataset.objects.create(project=self.project,name='Data',source_name='fixture',status='ready',
            schema_snapshot=self.schema,headers=['name'],row_count=2)
        self.rows=[DatasetRow.objects.create(dataset=self.dataset,row_number=i,values={'name':name})
            for i,name in [(2,'Alice'),(3,'Bob')]]

    def url(self,action,row=None):
        return reverse('dataset-row-'+action,args=[self.project.pk,self.dataset.pk,(row or self.rows[0]).pk])

    def action(self,action,row=None,revision=None):
        row=row or self.rows[0]
        return self.client.post(self.url(action,row),{'revision':revision or row_revision(row)})

    def test_view_delete_restore_and_queue_exclusion(self):
        self.assertContains(self.client.get(self.url('detail')),'Alice')
        self.client.get(self.url('delete'))
        self.rows[0].refresh_from_db()
        self.assertIsNone(self.rows[0].deleted_at)
        self.assertEqual(self.action('delete').status_code,302)
        self.rows[0].refresh_from_db()
        self.assertIsNotNone(self.rows[0].deleted_at)
        page=self.client.get(reverse('dataset-detail',args=[self.project.pk,self.dataset.pk]))
        self.assertNotContains(page,'Alice')
        deleted=self.client.get(reverse('dataset-detail',args=[self.project.pk,self.dataset.pk]),{'deleted':'1'})
        self.assertContains(deleted,'Alice')
        self.assertContains(deleted,'Restore')
        run=create_run(self.dataset,'ROBOT_INPUT_CRUD')
        queue=DjangoQueue(run)
        self.assertEqual([row.values['name'] for row in queue.rows()],['Bob'])
        queue.emit('run_completed',summary=RunResult(state=RunState.COMPLETED))
        self.assertEqual(self.action('restore').status_code,302)
        self.rows[0].refresh_from_db()
        self.assertIsNone(self.rows[0].deleted_at)
        self.assertEqual(self.rows[0].processing_status,'pending')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.row_count,2)

    def test_deletion_preserves_completed_inputs_outputs_and_history(self):
        robot=Robot.objects.create(project=self.project,name='ROBOT_INPUT_CRUD')
        run=create_run(self.dataset,robot.name)
        queue=DjangoQueue(run)
        queue.rows()
        queue.emit('row_started',row=str(self.rows[0].pk))
        result=RowResult(str(self.rows[0].pk),Outcome.OK,outputs={'result':'Hello, Alice!'})
        queue.emit('row_finished',row=result.reference,result=result)
        queue.emit('run_completed',summary=RunResult(state=RunState.COMPLETED,rows=[result]))
        self.rows[0].refresh_from_db()
        self.assertEqual(self.action('delete').status_code,302)
        attempt=run.attempts.get()
        self.assertEqual(attempt.input_snapshot,{'name':'Alice'})
        self.assertEqual(attempt.outputs,{'result':'Hello, Alice!'})
        page=self.client.get(self.url('detail'))
        self.assertContains(page,'Hello, Alice!')
        self.assertContains(page,'Restore input')
        self.rows[0].refresh_from_db()
        self.assertEqual(self.action('restore').status_code,302)
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].processing_status,'done')

    def test_active_execution_and_stale_confirmation_block_deletion(self):
        run=create_run(self.dataset,'ROBOT_INPUT_CRUD')
        self.assertContains(self.action('delete'),'Stop the active dataset execution')
        self.rows[0].refresh_from_db()
        self.assertIsNone(self.rows[0].deleted_at)
        DjangoQueue(run).emit('run_completed',summary=RunResult(state=RunState.COMPLETED))
        old=row_revision(self.rows[0])
        save_input(self.dataset,{'name':'Changed'},row_id=self.rows[0].pk,expected_revision=old)
        self.assertContains(self.action('delete',revision=old),'changed')
        self.rows[0].refresh_from_db()
        self.assertIsNone(self.rows[0].deleted_at)

    def test_deleted_rows_cannot_be_edited_and_invalid_restore_requires_preview(self):
        self.rows[0].errors=['Invalid value']
        self.rows[0].save()
        self.dataset.status='preview'
        self.dataset.invalid_row_count=1
        self.dataset.save()
        self.action('delete')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.invalid_row_count,0)
        self.client.post(reverse('dataset-confirm',args=[self.project.pk,self.dataset.pk]))
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status,'ready')
        self.assertContains(self.client.get(self.url('edit')),'locked')
        self.rows[0].refresh_from_db()
        self.action('restore')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status,'preview')
        self.assertEqual(self.dataset.invalid_row_count,1)

    def test_definition_detail_and_unused_delete_preserve_dataset_schema(self):
        url=reverse('input-detail',args=[self.project.pk,self.definition.pk])
        self.assertContains(self.client.get(url),'No workflow steps use this input')
        delete=reverse('input-delete',args=[self.project.pk,self.definition.pk])
        self.client.get(delete)
        self.assertTrue(ProjectInput.objects.filter(pk=self.definition.pk).exists())
        response=self.client.post(delete,{'revision':definition_revision(self.definition)})
        self.assertEqual(response.status_code,302)
        self.assertFalse(ProjectInput.objects.filter(pk=self.definition.pk).exists())
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.schema_snapshot,self.schema)
        self.assertEqual(self.dataset.rows.count(),2)

    def test_mapped_definition_and_stale_definition_delete_are_blocked(self):
        url=reverse('input-delete',args=[self.project.pk,self.definition.pk])
        old=definition_revision(self.definition)
        self.definition.description='Changed'
        self.definition.save()
        self.assertContains(self.client.post(url,{'revision':old}),'changed')
        WorkflowStep.objects.create(project=self.project,position=1,name='Fill',action='fill',input_column=self.definition)
        self.assertContains(self.client.post(url,{'revision':definition_revision(self.definition)}),'used by workflow steps')
        self.assertTrue(ProjectInput.objects.filter(pk=self.definition.pk).exists())

    def test_csrf_scoping_and_deleted_input_markup_are_safe(self):
        other=Project.objects.create(name='Other')
        for action in ('detail','delete','restore'):
            url=reverse('dataset-row-'+action,args=[other.pk,self.dataset.pk,self.rows[0].pk])
            self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get(reverse('input-detail',args=[other.pk,self.definition.pk])).status_code,404)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url('delete'),{'revision':row_revision(self.rows[0])}).status_code,403)
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('input-delete',args=[self.project.pk,self.definition.pk]),{'revision':definition_revision(self.definition)}).status_code,403)
        self.rows[0].values={'name':'<script>bad()</script>'}
        self.rows[0].save()
        self.assertContains(self.client.get(self.url('detail')),'&lt;script&gt;bad()&lt;/script&gt;')
