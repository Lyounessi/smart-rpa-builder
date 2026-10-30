from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase
from django.urls import reverse

from inspector.models import ApplicationWindow, CapturedElement
from projects.forms import StepForm
from projects.models import Project, WorkflowStep, StepElementReference, Dataset, DatasetRow
from projects.generation_context import assemble_generation_context
from robot_framework.base import BaseRobot
from robot_framework.context import RobotContext
from robot_framework.contracts import RunOptions, ExecutionCancelled
from muse_builder.validation import validate_source
from .adapters import DjangoQueue, create_run


class OutputTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Weather')
        self.window = ApplicationWindow.objects.create(project=self.project, name='Weather', target_url='https://example.invalid')
        self.element = CapturedElement.objects.create(window=self.window, name='Temperature', locator={'strategy':'label','value':'Temperature'})
        self.step = WorkflowStep.objects.create(project=self.project, window=self.window, position=1,
            name='Read weather', action='read_text', output_key='weather', instruction='Read weather text')
        StepElementReference.objects.create(step=self.step, element=self.element)
        self.dataset = Dataset.objects.create(project=self.project, name='Cities',source_name='cities.csv',
            schema_snapshot=[], headers=['city'], status='ready', row_count=2)
        self.rows = [DatasetRow.objects.create(dataset=self.dataset, row_number=i, values={'city':'City'}) for i in (2,3)]

    def test_step_form_context_and_output_names(self):
        data = {'name':'Read weather','instruction':'Read text','window':self.window.pk,'target':self.element.pk,
                'action':'read_text','output_key':'temperature'}
        form = StepForm(data, instance=self.step, project=self.project)
        self.assertTrue(form.is_valid(),form.errors)
        step = form.save()
        self.assertIsNone(step.input_column_id)
        context = assemble_generation_context(self.project, framework_contract='test')
        self.assertEqual(context['project_context']['steps'][0]['output_key'],'temperature')
        for bad in ['', 'not a name', '1invalid']:
            form = StepForm({**data, 'output_key':bad}, instance=step, project=self.project)
            self.assertFalse(form.is_valid())
        other = WorkflowStep(project=self.project,position=2,name='Other',action='read_text',output_key='temperature')
        with self.assertRaises(ValidationError):
            other.full_clean()

    def execute(self, *, notification_failure=False, row_failure=False):
        run = create_run(self.dataset,'ROBOT_WEATHER')
        queue = DjangoQueue(run)
        browser, cancel = Mock(), Mock()
        browser.read_text.side_effect = ['<script>21 C</script>','22 C']
        cancel.requested.return_value = False
        ctx = RobotContext(browser,Mock(),queue,cancel)
        element = str(self.element.pk)
        class Weather(BaseRobot):
            def process(self, ctx, inputs):
                with ctx.step('read_weather'):
                    ctx.extract_text(element,'weather')
                    if row_failure:
                        raise RuntimeError('Failure after extraction')
                    ctx.business_completed()
                    if notification_failure:
                        raise RuntimeError('Notification failure')
        result = Weather().execute(ctx,queue.rows(),RunOptions())
        return run, result, ctx

    def test_per_row_outputs_persist_and_render_escaped_without_changing_inputs(self):
        run,result,ctx = self.execute()
        self.assertEqual([row.outputs for row in result.rows],[{'weather':'<script>21 C</script>'},{'weather':'22 C'}])
        attempts = list(run.attempts.order_by('row__row_number'))
        self.assertEqual([item.outputs for item in attempts],[row.outputs for row in result.rows])
        page = self.client.get(reverse('run-detail',args=[run.pk]))
        self.assertContains(page,'&lt;script&gt;21 C&lt;/script&gt;')
        self.assertNotContains(page,'<script>21 C</script>')
        for row in self.rows:
            row.refresh_from_db()
            self.assertEqual(row.values,{'city':'City'})
            self.assertEqual(row.processing_status,'done')

    def test_business_checkpoint_keeps_output_when_notification_fails(self):
        run,result,ctx = self.execute(notification_failure=True)
        attempt = run.attempts.get()
        self.assertEqual(attempt.outcome,'ERROR')
        self.assertTrue(attempt.business_completed_at)
        self.assertEqual(attempt.outputs,{'weather':'<script>21 C</script>'})
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].processing_status,'done')

    def test_partial_failed_attempt_retains_output_but_row_remains_pending(self):
        run,result,ctx = self.execute(row_failure=True)
        self.assertEqual(run.attempts.get().outputs,{'weather':'<script>21 C</script>'})
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].processing_status,'pending')

    def test_checkpoint_saves_outputs_before_any_row_finished_event(self):
        run = create_run(self.dataset,'ROBOT_WEATHER')
        queue = DjangoQueue(run)
        queue.emit('row_started',row=str(self.rows[0].pk))
        browser,cancel = Mock(),Mock()
        cancel.requested.return_value=False
        browser.read_text.return_value='21 C'
        ctx = RobotContext(browser,Mock(),queue,cancel)
        ctx.row=str(self.rows[0].pk)
        ctx.extract_text(str(self.element.pk),'weather')
        ctx.business_completed()
        attempt=run.attempts.get()
        self.assertEqual(attempt.outputs,{'weather':'21 C'})
        self.assertEqual(attempt.outcome,'')
        self.assertIsNotNone(attempt.business_completed_at)
        with self.assertRaises(ValueError):
            ctx.extract_text(str(self.element.pk),'other')

    def test_static_validation_requires_extraction_with_matching_output_and_target(self):
        spec = {'project_context':assemble_generation_context(self.project,framework_contract='test')['project_context'],
                'decisions':{'setup_step_ids':[],'per_row_step_ids':[self.step.pk],'stop_on_nok':True,'stop_on_error':True}}
        source = f'''from robot_framework.base import BaseRobot
class ROBOT_WEATHER(BaseRobot):
    def setup(self, ctx):
        pass
    def process(self, ctx, inputs):
        with ctx.step("weather"):
            ctx.extract_text("{self.element.pk}", "weather")
            ctx.assert_visible("{self.element.pk}")
'''
        self.assertEqual(validate_source(source,robot_name='ROBOT_WEATHER',specification=spec),[])
        for bad in [source.replace('"weather")','"unknown")'), source.replace('ctx.extract_text','ctx.select_option'),
                    source.replace('ctx.extract_text','ctx.read_text')]:
            self.assertTrue(validate_source(bad,robot_name='ROBOT_WEATHER',specification=spec))

    def test_run_final_output_persists_without_changing_row_outputs(self):
        run = create_run(self.dataset,'ROBOT_WEATHER')
        queue = DjangoQueue(run)
        browser,cancel = Mock(),Mock()
        cancel.requested.return_value=False
        browser.read_text.return_value='Congratulations'
        element = str(self.element.pk)
        class Robot(BaseRobot):
            def process(self, ctx, inputs):
                pass
            def finalize(self, ctx):
                ctx.extract_text(element,'final_result')
        result = Robot().execute(RobotContext(browser,None,queue,cancel),queue.rows(),RunOptions())
        queue.emit('run_completed',summary=result)
        run.refresh_from_db()
        self.assertEqual(run.outputs,{'final_result':'Congratulations'})
        self.assertEqual(list(run.attempts.values_list('outputs',flat=True)),[{},{}])
        self.assertContains(self.client.get(reverse('run-detail',args=[run.pk])),'Congratulations')

    def test_final_extraction_must_stay_in_its_confirmed_phase(self):
        spec = {'project_context':assemble_generation_context(self.project,framework_contract='test')['project_context'],
            'decisions':{'setup_step_ids':[],'per_row_step_ids':[],'finalization_step_ids':[self.step.pk],
                'stop_on_nok':True,'stop_on_error':True}}
        source = f'''from robot_framework.base import BaseRobot
class ROBOT_WEATHER(BaseRobot):
    def setup(self, ctx):
        pass
    def process(self, ctx, inputs):
        with ctx.step("row"):
            ctx.assert_visible("{self.element.pk}")
    def finalize(self, ctx):
        with ctx.step("final"):
            ctx.extract_text("{self.element.pk}", "weather")
'''
        self.assertEqual(validate_source(source,robot_name='ROBOT_WEATHER',specification=spec),[])
        bad = source.replace('    def finalize(self, ctx):\n','')
        self.assertTrue(validate_source(bad,robot_name='ROBOT_WEATHER',specification=spec))


class ExtractionBoundaryTests(SimpleTestCase):
    def test_active_row_bounds_duplicate_names_and_cancellation(self):
        browser,cancel = Mock(),Mock()
        cancel.requested.return_value=False
        ctx = RobotContext(browser,Mock(),Mock(),cancel)
        with self.assertRaises(ValueError):
            ctx.extract_text('element','weather')
        ctx.row='1'
        browser.read_text.return_value='x'*16385
        with self.assertRaises(ValueError):
            ctx.extract_text('element','weather')
        self.assertEqual(ctx.outputs,{})
        browser.read_text.return_value='21 C'
        self.assertEqual(ctx.extract_text('element','weather'),'21 C')
        with self.assertRaises(ValueError):
            ctx.extract_text('element','weather')
        with self.assertRaises(ValueError):
            ctx.extract_text('element','bad name')
        ctx.outputs = {}
        cancel.requested.return_value=True
        browser.read_text.reset_mock()
        with self.assertRaises(ExecutionCancelled):
            ctx.extract_text('element','weather')
        browser.read_text.assert_not_called()
        cancel.requested.return_value=False
        browser.read_text.return_value='x'*16384
        for key in ('a','b','c','d'):
            ctx.extract_text('element',key)
        with self.assertRaises(ValueError):
            ctx.extract_text('element','e')
