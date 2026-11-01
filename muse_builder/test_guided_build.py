import json
from types import SimpleNamespace
from unittest.mock import Mock,patch

from django.test import TestCase,override_settings
from django.urls import reverse

from inspector.models import ApplicationWindow,CapturedElement
from projects.models import Project,ProjectInput,WorkflowStep,StepElementReference
from .client import MuseError
from .context import request_context,canonical
from .conversation import prepare_local_plan,conversation_state,queue_review,run_review,revision
from .forms import SpecificationForm
from .models import BuildSession,BuildOperation,BuildQuestion,MuseRequest


def make_guided_project():
    project=Project.objects.create(name='Registration demo',automation_goal='Register every supplier and verify completion')
    window=ApplicationWindow.objects.create(project=project,name='Registration form',target_url='https://example.invalid/')
    column=ProjectInput.objects.create(project=project,key='name')
    steps=[]
    for index,(name,action) in enumerate([('Start','click'),('Name','fill'),('Submit','click'),('Congratulations','read_text')],1):
        element=CapturedElement.objects.create(window=window,name=name,locator={'strategy':'css','value':f'[data-testid="target-{index}"]'},
            selector_quality={'large_diagnostic':'test evidence '*100,'verified_candidates':[{'strategy':'css','value':'.candidate'}]})
        step=WorkflowStep.objects.create(project=project,window=window,position=index,name=name,action=action,
            instruction=f'{action} {name}',input_column=column if action=='fill' else None,
            output_key='congrats' if action=='read_text' else '')
        StepElementReference.objects.create(step=step,element=element)
        steps.append(step)
    return project,steps


@override_settings(MUSE_APIKEY='fictional-api-key',META_MODEL='muse-spark-1.3',MUSE_MAX_OUTPUT_TOKENS='4096')
class GuidedBuildTests(TestCase):
    def setUp(self):
        self.project,self.steps=make_guided_project()

    def guided_data(self,session):
        return {'guided_plan':'1','revision':revision(session),
            **{f'phase_{step.pk}':phase for step,phase in zip(self.steps,['setup','per_row','per_row','finalization'])},
            'stop_on_nok':'true','stop_on_error':'true',
            'success_criteria':'After Submit the round changes OR completion appears; verify final Congratulations.',
            'rejection_handling':'Stop on rejection; do not retry Submit.','recovery_plan':''}

    def test_prepare_save_confirm_is_free_without_provider_or_worker(self):
        with patch('muse_builder.client.MetaClient.request',side_effect=AssertionError('No API call')):
            page=self.client.get(reverse('muse-build',args=[self.project.pk]))
            self.assertContains(page,'Prepare my plan (no API call)')
            self.assertNotContains(page,'comes in Phase 4')
            self.assertFalse(BuildSession.objects.exists())
            response=self.client.post(reverse('muse-plan-prepare',args=[self.project.pk]))
            self.assertEqual(response.status_code,302)
            session=BuildSession.objects.get()
            self.assertEqual(session.decisions['per_row_step_ids'],[self.steps[1].pk])
            self.assertIsNone(session.confirmed_at)
            saved=self.client.post(reverse('muse-specification-edit',args=[self.project.pk,session.pk]),self.guided_data(session))
            self.assertEqual(saved.status_code,302)
            session.refresh_from_db()
            self.assertEqual(session.state,'ready_to_generate')
            self.assertEqual(session.decisions['finalization_step_ids'],[self.steps[3].pk])
            self.assertFalse(any(key.startswith('phase_') for key in session.decisions))
            self.client.post(reverse('muse-specification-confirm',args=[self.project.pk,session.pk]),{'revision':revision(session)})
            session.refresh_from_db()
            self.assertIsNotNone(session.confirmed_at)
            self.assertFalse(BuildOperation.objects.exists())
            self.assertFalse(MuseRequest.objects.exists())
            self.assertContains(self.client.get(response.url),'Generate draft robot (paid API requests)')

    def test_missing_targets_block_preparation_and_paid_review(self):
        self.steps[0].element_references.all().delete()
        response=self.client.post(reverse('muse-plan-prepare',args=[self.project.pk]))
        self.assertContains(response,'capture a target element')
        self.assertFalse(BuildSession.objects.exists())
        with patch('muse_builder.conversation.launch') as launch:
            self.client.post(reverse('muse-build-start',args=[self.project.pk]))
        launch.assert_not_called()
        self.assertFalse(BuildOperation.objects.exists())

    @override_settings(MUSE_APIKEY='')
    def test_local_plan_does_not_need_provider_credentials(self):
        session=prepare_local_plan(self.project)
        self.assertIsNone(session.confirmed_at)
        page=self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page,'Save plan (no API call)')
        self.assertContains(page,'Muse is not configured')
        self.assertFalse(MuseRequest.objects.exists())

    def test_invalid_or_missing_phase_and_foreign_mapping_cannot_be_saved(self):
        session=prepare_local_plan(self.project)
        for change in [{f'phase_{self.steps[0].pk}':''},{f'phase_{self.steps[0].pk}':'invented'},
            {f'phase_{self.steps[1].pk}':'setup'}]:
            form=SpecificationForm({**self.guided_data(session),**change},project=self.project,guided=True)
            self.assertFalse(form.is_valid())
        stale=self.guided_data(session)
        stale['revision']='outdated'
        self.assertContains(self.client.post(reverse('muse-specification-edit',args=[self.project.pk,session.pk]),stale),'out of date')

    def test_compact_clarification_omits_diagnostics_and_example_but_keeps_contract_and_ids(self):
        session=prepare_local_plan(self.project)
        full_instructions,full=request_context(session.snapshot,include_images=False)
        compact_instructions,compact=request_context(session.snapshot,include_images=False,compact=True)
        text=compact[0]['content'][0]['text']
        self.assertNotIn('large_diagnostic',text)
        self.assertNotIn('verified_candidates',text)
        self.assertNotIn('ExampleRobot',compact_instructions)
        self.assertIn('wait_for_progress',compact_instructions)
        for step in self.steps:
            self.assertIn(str(step.element_references.get().element_id),text)
        self.assertLess(len(compact_instructions)+len(canonical(compact)),len(full_instructions)+len(canonical(full)))
        self.assertIn('large_diagnostic',canonical(session.snapshot.project_data))

    def test_resolved_answers_sent_and_identical_questions_not_reopened(self):
        session=prepare_local_plan(self.project)
        from .models import BuildMessage
        old=BuildMessage.objects.create(session=session,role='assistant',content='Old question')
        question=BuildQuestion.objects.create(session=session,message=old,key='old_success',text='What proves success?',
            answer='Round advances or completion appears.',resolved=True)
        state=conversation_state(session)
        self.assertEqual(state['resolved_questions'][0]['answer'],question.answer)
        operation=queue_review(session,content='Review only missing decisions')
        service=Mock()
        service.clarify.return_value=SimpleNamespace(text=json.dumps({'state':'needs_clarification',
            'questions':[{'id':'new_success','text':'What proves success?','choices':[]}],
            'proposed_changes':[],'resolved_question_ids':[],'summary':'Review success.',
            'assumptions':[],'unsupported_requests':[]}))
        run_review(operation.pk,service=service)
        self.assertEqual(session.questions.count(),1)
        self.assertFalse(session.questions.filter(resolved=False).exists())
        operation.refresh_from_db()
        self.assertEqual(operation.status,'success')

    def test_three_round_limit_keeps_local_guided_editor_available(self):
        session=prepare_local_plan(self.project)
        session.rounds_used=3
        session.save()
        page=self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page,'Save plan (no API call)')
        self.assertNotContains(page,'Send answers for review (paid API request)')
        with self.assertRaises(MuseError):
            queue_review(session,content='Fourth request')

    def test_provider_failure_is_visible_without_starting_another_request(self):
        session=prepare_local_plan(self.project)
        session.state='failed'
        session.error_message='Could not reach Meta. No automatic retry was made.'
        session.save()
        page=self.client.get(reverse('muse-build',args=[self.project.pk]))
        self.assertContains(page,'Could not reach Meta. No automatic retry was made.')
        self.assertFalse(BuildOperation.objects.exists())
        self.assertFalse(MuseRequest.objects.exists())
