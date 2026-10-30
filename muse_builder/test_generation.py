import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from execution.models import RobotBuild, RobotRun
from inspector.models import ApplicationWindow, CapturedElement
from projects.models import Project, ProjectInput, WorkflowStep, StepElementReference
from .client import MuseError
from .conversation import confirm_specification, launch, queue_review, revision, save_decisions, start_session
from .forms import SpecificationForm
from .generation import queue_generation, run_generation
from .models import BuildOperation, MuseRequest
from .service import MuseService
from .validation import validate_source


@override_settings(MUSE_APIKEY='fictional-api-key', META_MODEL='muse-spark-1.3',
                   MUSE_MAX_OUTPUT_TOKENS='4096', MUSE_GENERATION_OUTPUT_TOKENS='4096')
class GenerationTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Supplier Test')
        self.window = ApplicationWindow.objects.create(project=self.project, name='Portal', target_url='https://example.invalid/')
        self.column = ProjectInput.objects.create(project=self.project, key='name')
        self.element = CapturedElement.objects.create(window=self.window, name='Name', locator={'strategy':'label','value':'Name'})
        self.step = WorkflowStep.objects.create(project=self.project, window=self.window, position=1,
            name='Fill name', instruction='Fill the name', action='fill', input_column=self.column)
        StepElementReference.objects.create(step=self.step, element=self.element)
        with patch('muse_builder.conversation.launch'):
            self.session = start_session(self.project)
        self.session.operations.update(active_slot=None, status='success')
        form = SpecificationForm({'setup_step_ids':[], 'per_row_step_ids':[self.step.pk],
            'stop_on_nok':'true','stop_on_error':'true','success_criteria':'Name is visible',
            'rejection_handling':'Stop on duplicates','recovery_plan':'','resolve_questions':'on'}, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        self.session = save_decisions(self.session, form)
        self.session = confirm_specification(self.session)
        self.source = f'''from robot_framework.base import BaseRobot
class ROBOT_SUPPLIER_TEST(BaseRobot):
    def setup(self, ctx):
        ctx.navigate({self.window.pk})
    def process(self, ctx, inputs):
        with ctx.step("Fill name"):
            ctx.fill("{self.element.pk}", inputs["name"])
        ctx.assert_visible("{self.element.pk}")
'''

    def response(self, source=None, questions=None):
        return json.dumps({'source_code':self.source if source is None else source,
                           'assumptions':[], 'clarification_questions':questions or []})

    def service(self, *responses):
        service = Mock()
        service.generate_draft.side_effect = [SimpleNamespace(text=text) for text in responses]
        return service

    def validate(self, source):
        return validate_source(source, robot_name='ROBOT_SUPPLIER_TEST', specification=self.session.confirmed_specification)

    def test_input_inner_text_is_rejected_but_input_value_supported(self):
        bad = self.source + f'        ctx.read_text("{self.element.pk}")\n'
        self.assertTrue(any('input value' in error for error in self.validate(bad)))
        self.assertEqual(self.validate(bad.replace('ctx.read_text','ctx.read_value')),[])

    def test_refresh_preserves_old_confirmation_without_api_and_requires_new_confirmation(self):
        from .conversation import refresh_specification
        old_hash = self.session.confirmed_hash
        current = refresh_specification(self.session)
        self.assertIsNone(current.confirmed_at)
        self.assertFalse(current.manual_reviewed)
        self.assertEqual(current.decisions['finalization_step_ids'],[])
        self.assertFalse(current.operations.exists())
        self.session.refresh_from_db()
        self.assertEqual(self.session.confirmed_hash,old_hash)

    def test_valid_source_saved_as_new_draft_without_execution_and_get_is_free(self):
        self.assertEqual(self.validate(self.source), [])
        for version in (1,2):
            self.session.refresh_from_db()
            operation = queue_generation(self.session, expected_revision=revision(self.session))
            service = self.service(self.response())
            with patch('robot_framework.base.BaseRobot.execute', side_effect=AssertionError('must not execute')):
                run_generation(operation.generation_id, service=service)
            run_generation(operation.generation_id, service=service)
            self.assertEqual(service.generate_draft.call_count, 1)
            build = RobotBuild.objects.get(version=version)
            self.assertTrue(build.is_draft)
            self.assertEqual(build.confirmed_specification_hash, self.session.confirmed_hash)
            self.assertEqual(build.source_files['ROBOT_SUPPLIER_TEST.py'], self.source)
            page = self.client.get(reverse('robot-build-detail',args=[build.robot_id, version]))
            self.assertContains(page, 'not activated')
            self.assertContains(page, self.session.confirmed_hash)
        self.assertFalse(RobotRun.objects.exists())
        self.assertFalse(MuseRequest.objects.exists())
        page = self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page, 'Open draft version 2')
        self.assertNotContains(page, 'hx-trigger="every 2s"')

    def test_two_repairs_maximum_and_failed_sources_remain_reviewable(self):
        operation = queue_generation(self.session)
        service = self.service(*[self.response('print("<script>bad</script>")')] * 3)
        run_generation(operation.generation_id, service=service)
        job = operation.generation
        job.refresh_from_db()
        self.assertEqual(job.state, 'failed')
        self.assertEqual(service.generate_draft.call_count, 3)
        self.assertEqual(list(job.operations.order_by('round_number').values_list('kind',flat=True)), ['generation','repair','repair'])
        self.assertFalse(BuildOperation.objects.filter(active_slot='local').exists())
        self.assertFalse(RobotBuild.objects.exists())
        page = self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page, '&lt;script&gt;bad&lt;/script&gt;')

    def test_invalid_structure_can_be_repaired_once(self):
        operation = queue_generation(self.session)
        service = self.service('not JSON', self.response())
        run_generation(operation.generation_id, service=service)
        self.assertEqual(service.generate_draft.call_count, 2)
        self.assertEqual(RobotBuild.objects.count(), 1)
        self.assertTrue(service.generate_draft.call_args.kwargs['errors'])

    def test_blocking_questions_return_to_clarification_without_a_build(self):
        operation = queue_generation(self.session)
        run_generation(operation.generation_id, service=self.service(self.response('', ['Which result confirms success?'])))
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, 'needs_clarification')
        self.assertIsNone(self.session.confirmed_at)
        self.assertEqual(self.session.questions.get(resolved=False).text, 'Which result confirms success?')
        self.assertFalse(RobotBuild.objects.exists())
        next_review = queue_review(self.session, content='The result must show accepted.')
        self.assertEqual(next_review.kind, 'clarification')
        self.assertGreater(next_review.round_number, operation.round_number)

    def test_generation_launch_and_abandoned_recovery(self):
        operation = queue_generation(self.session)
        with patch('muse_builder.conversation.subprocess.Popen') as process:
            launch(operation)
        self.assertEqual(process.call_args.args[0][-2:], ['generate_muse_robot', str(operation.generation_id)])
        call_command('close_abandoned_build_review', str(operation.pk), '--worker-stopped')
        operation.refresh_from_db()
        self.assertIsNone(operation.active_slot)
        job = operation.generation
        job.refresh_from_db()
        self.assertEqual(job.state, 'failed')

    def test_stale_context_before_and_during_response_is_rejected(self):
        operation = queue_generation(self.session)
        self.project.automation_goal = 'Changed'
        self.project.save()
        service = self.service(self.response())
        run_generation(operation.generation_id, service=service)
        service.generate_draft.assert_not_called()
        self.assertFalse(RobotBuild.objects.exists())

    def test_context_changed_during_response_discards_paid_result(self):
        operation = queue_generation(self.session)
        service = Mock()
        def result(*args, **kwargs):
            Project.objects.filter(pk=self.project.pk).update(automation_goal='Changed during request')
            return SimpleNamespace(text=self.response())
        service.generate_draft.side_effect = result
        run_generation(operation.generation_id, service=service)
        self.assertFalse(RobotBuild.objects.exists())
        self.assertEqual(service.generate_draft.call_count, 1)

    def test_provider_failure_does_not_retry(self):
        operation = queue_generation(self.session)
        service = Mock()
        service.generate_draft.side_effect = MuseError('timeout','Request timed out.')
        run_generation(operation.generation_id, service=service)
        self.assertEqual(service.generate_draft.call_count, 1)
        self.assertFalse(RobotBuild.objects.exists())

    def test_local_validation_failure_preserves_paid_response_and_safe_diagnostic(self):
        operation = queue_generation(self.session)
        client = Mock()
        client.request.return_value = SimpleNamespace(status='completed', output_text=self.response(),
            usage=SimpleNamespace(input_tokens=100,output_tokens=100,input_tokens_details=SimpleNamespace(cached_tokens=0)))
        with patch('muse_builder.generation.validate_source',side_effect=TypeError('fictional-api-key')):
            with self.assertLogs('muse_builder.generation',level='ERROR') as logs:
                run_generation(operation.generation_id,service=MuseService(client=client))
        operation.refresh_from_db()
        self.assertEqual(operation.response_payload['source_code'],self.source)
        self.assertIn('static_validation (TypeError)', operation.error_message)
        self.assertIn('Recorded API usage is retained',operation.error_message)
        self.assertNotIn('fictional-api-key', ''.join(logs.output) + operation.error_message)
        request = MuseRequest.objects.get(build_operation=operation)
        self.assertEqual(request.error_code,'local_processing')
        self.assertTrue(request.usage_known)
        self.assertIsNone(request.active_slot)
        self.assertEqual(client.request.call_count,1)
        self.assertFalse(RobotBuild.objects.exists())

    def test_local_save_failure_retains_source_outside_rolled_back_transaction(self):
        operation = queue_generation(self.session)
        with patch('muse_builder.generation.save_draft',side_effect=RuntimeError('internal detail')):
            with self.assertLogs('muse_builder.generation',level='ERROR'):
                run_generation(operation.generation_id,service=self.service(self.response()))
        operation.refresh_from_db()
        self.assertEqual(operation.response_payload['source_code'],self.source)
        self.assertIn('draft_save (RuntimeError)',operation.error_message)
        self.assertFalse(RobotBuild.objects.exists())

    def test_post_only_scoped_csrf_and_confirmed_revision_required(self):
        url = reverse('muse-generate',args=[self.project.pk,self.session.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code, 403)
        other = Project.objects.create(name='Other')
        self.assertEqual(self.client.post(reverse('muse-generate',args=[other.pk,self.session.pk])).status_code,404)
        with patch('muse_builder.build_views.launch') as launch:
            self.client.post(url, {'revision':'outdated'})
            launch.assert_not_called()
            self.assertEqual(self.client.post(url, {'revision':revision(self.session)}).status_code,302)
            launch.assert_called_once()
        with self.assertRaises(MuseError):
            queue_generation(self.session)

    def test_unconfirmed_specification_cannot_generate(self):
        self.session.confirmed_at = None
        self.session.save()
        with self.assertRaises(MuseError):
            queue_generation(self.session)

    def test_each_attempt_uses_existing_budget_ledger_with_its_own_request(self):
        operation = queue_generation(self.session)
        client = Mock()
        client.request.side_effect = [SimpleNamespace(status='completed',output_text=text,
            usage=SimpleNamespace(input_tokens=100,output_tokens=100,input_tokens_details=SimpleNamespace(cached_tokens=0)))
            for text in [self.response('not valid Python!'), self.response()]]
        run_generation(operation.generation_id, service=MuseService(client=client))
        requests = list(MuseRequest.objects.order_by('created_at'))
        self.assertEqual([item.operation for item in requests], ['generation','repair'])
        self.assertTrue(all(item.usage_known and item.accounted_usd > 0 and item.active_slot is None for item in requests))
        self.assertNotEqual(requests[0].build_operation_id, requests[1].build_operation_id)
        self.assertEqual(RobotBuild.objects.count(), 1)
        self.assertEqual(client.request.call_args.kwargs['response_schema']['additionalProperties'], False)

    def test_known_secret_response_is_never_persisted(self):
        operation = queue_generation(self.session)
        service = self.service(self.response(self.source + '\n# fictional-api-key'))
        run_generation(operation.generation_id, service=service)
        operation.refresh_from_db()
        self.assertEqual(operation.response_payload, {})
        self.assertFalse(RobotBuild.objects.exists())

    def test_budget_failure_between_attempts_stops_without_extra_repairs(self):
        operation = queue_generation(self.session)
        service = Mock()
        service.generate_draft.side_effect = [SimpleNamespace(text=self.response('invalid!')),
            MuseError('budget_exhausted','Spending limit reached.')]
        run_generation(operation.generation_id, service=service)
        self.assertEqual(service.generate_draft.call_count, 2)
        self.assertFalse(RobotBuild.objects.exists())
        self.assertFalse(BuildOperation.objects.filter(active_slot='local').exists())

    def test_static_validation_rejects_incompatible_code(self):
        cases = [self.source.replace('ROBOT_SUPPLIER_TEST','WRONG_NAME'),
                 'import os\n' + self.source, 'print("run")\n' + self.source,
                 self.source.replace('inputs["name"]','inputs["unknown"]'),
                 self.source.replace(str(self.element.pk),'unknown-id'),
                 self.source.replace('def process(self, ctx, inputs):','def execute(self, ctx, inputs):'),
                 self.source.replace('ctx.fill(', 'ctx.browser.fill('),
                 self.source.replace('inputs["name"]','"hardcoded"'),
                 self.source.replace('ctx.assert_visible','ctx.click')]
        for source in cases:
            with self.subTest(source=source[:70]):
                self.assertTrue(self.validate(source))

    def test_continuation_requires_explicit_verified_recovery(self):
        self.session.confirmed_specification['decisions']['stop_on_nok'] = False
        self.assertTrue(self.validate(self.source))
        recovery = f'    def recover(self, ctx, outcome):\n        ctx.assert_visible("{self.element.pk}")\n        return True\n'
        self.assertEqual(self.validate(self.source + recovery), [])
