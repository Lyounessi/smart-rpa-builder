import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from pydantic import ValidationError as SchemaError

from inspector.models import ApplicationWindow, CapturedElement
from projects.models import Project, ProjectInput, StepElementReference, WorkflowStep
from .client import MuseError
from .conversation import (confirm_specification, conversation_state, queue_review, review_proposals,
                           run_review, save_decisions, start_session)
from .conversation_schema import ClarificationResponse, provider_schema
from .forms import SpecificationForm
from .models import BuildMessage, BuildOperation, BuildSession, MuseRequest


@override_settings(MUSE_APIKEY='fictional-api-key', META_MODEL='muse-spark-1.3', MUSE_MAX_OUTPUT_TOKENS='4096')
class ConversationTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Conversation fixture', automation_goal='Create suppliers')
        self.window = ApplicationWindow.objects.create(project=self.project, name='Portal', target_url='https://example.invalid/')
        self.column = ProjectInput.objects.create(project=self.project, key='name')
        self.element = CapturedElement.objects.create(window=self.window, name='Name', locator={'strategy':'label','value':'Name'})
        self.step = WorkflowStep.objects.create(project=self.project, window=self.window, position=1, name='Fill name',
            instruction='Fill name from name input', action='fill', input_column=self.column)
        StepElementReference.objects.create(step=self.step, element=self.element)

    def response(self, **overrides):
        body = {'state':'needs_clarification','questions':[],'proposed_changes':[],'resolved_question_ids':[],
                'summary':'Review the saved workflow.','assumptions':[],'unsupported_requests':[]}
        body.update(overrides)
        return body

    def proposal(self, field, value, step_id=None):
        return {'field':field,'step_id':step_id,'value':value,'reason':'Confirm this workflow decision.'}

    def complete_proposals(self):
        return [self.proposal('setup_step_ids','[]'),self.proposal('per_row_step_ids',json.dumps([self.step.pk])),
                self.proposal('stop_on_nok','true'),self.proposal('stop_on_error','true'),
                self.proposal('success_criteria','The created supplier reference is visible'),
                self.proposal('rejection_handling','Stop on a known duplicate supplier'),self.proposal('recovery_plan','')]

    def start(self):
        with patch('muse_builder.conversation.launch') as launch:
            session = start_session(self.project)
        launch.assert_called_once()
        return session

    def review(self, session, body):
        service = Mock()
        service.clarify.return_value = SimpleNamespace(text=json.dumps(body))
        operation = session.operations.get(active_slot='local')
        run_review(operation.pk, service=service)
        session.refresh_from_db()
        operation.refresh_from_db()
        return service, operation

    def valid_form(self):
        form = SpecificationForm({'setup_step_ids':[], 'per_row_step_ids':[self.step.pk],
            'stop_on_nok':'true','stop_on_error':'true','success_criteria':'Supplier reference visible',
            'rejection_handling':'Stop on duplicates','recovery_plan':'','resolve_questions':'on'}, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        return form

    def test_get_is_free_and_start_only_queues_a_worker(self):
        response = self.client.get(reverse('muse-build', args=[self.project.pk]))
        self.assertContains(response, 'Review workflow with Muse')
        self.assertEqual(BuildSession.objects.count(), 0)
        with patch('muse_builder.conversation.launch') as launch:
            response = self.client.post(reverse('muse-build-start',args=[self.project.pk]))
        self.assertEqual(response.status_code, 302)
        launch.assert_called_once()
        self.assertEqual(BuildOperation.objects.get().status, 'queued')
        self.assertEqual(MuseRequest.objects.count(), 0)

    def test_questions_and_raw_message_are_preserved_and_no_settings_change(self):
        session = self.start()
        body = self.response(questions=[{'id':'success','text':'What proves success?','choices':['Reference exists','Status changes']}])
        self.review(session, body)
        self.assertEqual(session.questions.get().key, 'success')
        message = session.messages.get(role='assistant')
        self.assertEqual(json.loads(message.raw_response), body)
        self.project.refresh_from_db()
        self.assertEqual(self.project.success_criteria, '')
        page = self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page, 'What proves success?')
        self.assertNotContains(page, 'hx-trigger="every 2s"')

    def test_proposals_need_confirmation_and_generation_needs_final_confirmation(self):
        session = self.start()
        self.review(session, self.response(state='ready_to_generate', proposed_changes=self.complete_proposals()))
        self.assertEqual(session.decisions['per_row_step_ids'], [])
        with self.assertRaises(MuseError):
            confirm_specification(session)
        session = review_proposals(session, session.messages.get(role='assistant').pk, accept=True)
        self.assertEqual(session.state, 'ready_to_generate')
        self.assertIsNone(session.confirmed_at)
        session = confirm_specification(session)
        self.assertIsNotNone(session.confirmed_at)
        self.assertEqual(session.confirmed_specification['decisions']['per_row_step_ids'], [self.step.pk])
        self.assertEqual(len(session.confirmed_hash), 64)
        page = self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page, 'Agreed specification confirmed')
        self.assertContains(page, 'Generate draft robot (paid API requests)')

    def test_brief_and_step_changes_are_explicit_and_update_snapshot_after_confirmation(self):
        session = self.start()
        old_hash = session.snapshot.specification_hash
        self.review(session, self.response(proposed_changes=[self.proposal('automation_goal','New goal'),
            self.proposal('global_rules','No duplicate records'),self.proposal('step_instruction','Enter the mapped name',self.step.pk)]))
        self.project.refresh_from_db()
        self.step.refresh_from_db()
        self.assertEqual(self.project.automation_goal, 'Create suppliers')
        self.assertEqual(self.step.instruction, 'Fill name from name input')
        session = review_proposals(session, session.messages.get(role='assistant').pk, accept=True)
        self.project.refresh_from_db()
        self.step.refresh_from_db()
        self.assertEqual(self.project.automation_goal, 'New goal')
        self.assertEqual(self.project.global_rules, 'No duplicate records')
        self.assertEqual(self.step.instruction, 'Enter the mapped name')
        self.assertNotEqual(session.snapshot.specification_hash, old_hash)

    def test_rejected_and_manually_superseded_proposals_cannot_reapply(self):
        session = self.start()
        self.review(session, self.response(proposed_changes=[self.proposal('automation_goal','Never apply')]))
        message = session.messages.get(role='assistant')
        save_decisions(session, self.valid_form())
        message.refresh_from_db()
        self.assertEqual(message.review_status, 'rejected')
        url = reverse('muse-proposal-review',args=[self.project.pk,session.pk,message.pk])
        self.assertEqual(self.client.post(url, {'decision':'confirm'}).status_code, 404)
        self.project.refresh_from_db()
        self.assertEqual(self.project.automation_goal, 'Create suppliers')

    def test_foreign_or_incompatible_mapping_proposals_are_rejected(self):
        session = self.start()
        _, operation = self.review(session, self.response(proposed_changes=[self.proposal('step_input_mapping','foreign_key',self.step.pk)]))
        self.assertEqual(operation.status,'failed')
        self.assertEqual(session.proposals.count(),0)
        self.step.refresh_from_db()
        self.assertEqual(self.step.input_column_id,self.column.pk)

    def test_three_rounds_enforced_and_local_edit_remains_available(self):
        session = self.start()
        for index in range(3):
            self.review(session,self.response())
            if index < 2:
                queue_review(session,content='Clarify the workflow decisions')
        session.refresh_from_db()
        self.assertEqual(session.rounds_used,3)
        with self.assertRaises(MuseError) as caught:
            queue_review(session,content='Fourth review must be blocked')
        self.assertEqual(caught.exception.code,'round_limit')
        session = save_decisions(session,self.valid_form())
        self.assertEqual(session.state,'ready_to_generate')
        self.assertIsNotNone(confirm_specification(session).confirmed_at)

    def test_more_than_three_questions_and_unknown_fields_fail_schema_validation(self):
        body = self.response(questions=[{'id':f'q{i}','text':'Question','choices':[]} for i in range(4)])
        with self.assertRaises(SchemaError):
            ClarificationResponse.model_validate(body)
        body = self.response(proposed_changes=[self.proposal('shell_command','danger')])
        with self.assertRaises(SchemaError):
            ClarificationResponse.model_validate(body)
        schema = provider_schema()
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])
        for definition in schema['$defs'].values():
            self.assertFalse(definition['additionalProperties'])
            self.assertEqual(set(definition['required']),set(definition['properties']))

    def test_invalid_provider_output_fails_without_retry_or_partial_mutation(self):
        session = self.start()
        body = self.response(questions=[{'id':f'q{i}','text':'Question','choices':[]} for i in range(4)])
        service, operation = self.review(session,body)
        self.assertEqual(service.clarify.call_count,1)
        self.assertEqual(operation.status,'failed')
        self.assertIsNone(operation.active_slot)
        self.assertEqual(session.questions.count(),0)
        self.assertEqual(session.state,'failed')

    def test_unresolved_decisions_survive_context_compaction_and_answers_require_confirmation(self):
        session = self.start()
        self.review(session,self.response(questions=[{'id':'success','text':'What proves success?','choices':[]}]))
        question = session.questions.get()
        queue_review(session,content='success: A reference exists',answers={question.pk:'A reference exists'})
        self.review(session,self.response(resolved_question_ids=['success'], proposed_changes=[self.proposal('success_criteria','A reference exists')]))
        question.refresh_from_db()
        self.assertFalse(question.resolved)
        self.assertEqual(conversation_state(session)['outstanding_questions'][0]['answer'],'A reference exists')
        session = review_proposals(session,session.messages.filter(role='assistant').last().pk,accept=True)
        question.refresh_from_db()
        self.assertTrue(question.resolved)
        self.assertEqual(session.decisions['success_criteria'],'A reference exists')

    def test_unsupported_requests_block_manual_confirmation(self):
        session = self.start()
        self.review(session,self.response(unsupported_requests=['Outlook desktop automation is not supported']))
        with self.assertRaises(MuseError) as caught:
            save_decisions(session,self.valid_form())
        self.assertEqual(caught.exception.code,'unsupported')

    def test_stale_snapshot_blocks_edits_and_followups(self):
        session = self.start()
        self.review(session,self.response())
        self.project.global_rules = 'Changed after snapshot'
        self.project.save()
        with self.assertRaises(MuseError) as caught:
            queue_review(session,content='Must not send stale context')
        self.assertEqual(caught.exception.code,'stale_specification')
        with self.assertRaises(MuseError):
            save_decisions(session,self.valid_form())
        self.assertContains(self.client.get(reverse('muse-build',args=[self.project.pk])), 'Start a fresh review before continuing')

    def test_project_scoping_csrf_and_explicit_post_actions(self):
        session = self.start()
        foreign = Project.objects.create(name='Other')
        self.assertEqual(self.client.get(reverse('muse-build',args=[foreign.pk]),{'session':str(session.pk)}).status_code,404)
        url = reverse('muse-build-start',args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(url,{}).status_code,403)

    def test_missing_credentials_and_double_submit_do_not_spawn_extra_workers(self):
        with override_settings(MUSE_APIKEY=''),patch('muse_builder.conversation.launch') as launch:
            self.assertContains(self.client.post(reverse('muse-build-start',args=[self.project.pk])), 'Set MUSE_APIKEY')
        launch.assert_not_called()
        session = self.start()
        with self.assertRaises(MuseError):
            queue_review(session,content='Duplicate click')
        session.refresh_from_db()
        self.assertEqual(session.rounds_used,1)
        self.assertEqual(session.operations.count(),1)

    def test_confirmed_specification_is_invalidated_by_new_review(self):
        session = self.start()
        self.review(session,self.response())
        session = save_decisions(session,self.valid_form())
        session = confirm_specification(session)
        queue_review(session,content='Revisit the rejection policy')
        session.refresh_from_db()
        self.assertIsNone(session.confirmed_at)
        self.assertEqual(session.confirmed_specification,{})

    def test_stale_form_cannot_confirm_unseen_changes(self):
        from .conversation import revision
        session = self.start()
        self.review(session,self.response())
        token = revision(session)
        BuildMessage.objects.create(session=session,role='user',content='A newer decision from another tab')
        with self.assertRaises(MuseError) as caught:
            save_decisions(session,self.valid_form(),expected_revision=token)
        self.assertEqual(caught.exception.code,'stale_session')
        session.refresh_from_db()
        self.assertEqual(session.decisions['per_row_step_ids'],[])

    def test_unknown_question_resolution_and_html_are_handled_safely(self):
        session = self.start()
        self.review(session,self.response(resolved_question_ids=['unknown']))
        self.assertEqual(session.state,'failed')
        operation = queue_review(session,content='Please review again')
        self.review(session,self.response(summary='<script>alert(1)</script>'))
        page = self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page,'&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(page,'<script>alert(1)</script>')

    def test_suggested_answer_help_text_is_escaped(self):
        session = self.start()
        self.review(session,self.response(questions=[{'id':'check','text':'Choose success evidence','choices':['<script>bad()</script>']}]))
        page = self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page,'&lt;script&gt;bad()&lt;/script&gt;')
        self.assertNotContains(page,'<script>bad()</script>')

    def test_worker_uses_the_real_budget_service_with_mocked_provider(self):
        from .service import MuseService
        session = self.start()
        operation = session.operations.get()
        provider = Mock()
        provider.request.return_value = SimpleNamespace(status='completed', output_text=json.dumps(self.response()),
            usage=SimpleNamespace(input_tokens=300,output_tokens=50,input_tokens_details=SimpleNamespace(cached_tokens=0)))
        run_review(operation.pk,service=MuseService(client=provider))
        request = MuseRequest.objects.get(build_operation=operation)
        self.assertEqual(request.operation,'clarification')
        self.assertEqual(request.outcome,'success')
        self.assertIsNone(request.active_slot)
        self.assertGreater(request.estimated_cost_usd,0)
        self.assertIn('response_schema',provider.request.call_args.kwargs)
        self.assertIn('Conversation state:',str(provider.request.call_args.kwargs['input']))
        self.assertEqual(provider.request.call_count,1)

    def test_recovery_command_requires_stopped_worker_and_makes_no_api_call(self):
        from django.core.management.base import CommandError
        session = self.start()
        operation = session.operations.get()
        with self.assertRaises(CommandError):
            call_command('close_abandoned_build_review',str(operation.pk))
        call_command('close_abandoned_build_review',str(operation.pk),worker_stopped=True)
        operation.refresh_from_db()
        self.assertEqual(operation.status,'failed')
        self.assertIsNone(operation.active_slot)
