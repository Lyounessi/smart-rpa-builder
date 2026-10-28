from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from projects.models import Dataset, DatasetRow, Project
from robot_framework.adapters.email import FakeEmailAdapter
from robot_framework.base import BaseRobot
from robot_framework.contracts import InputRow, RunOptions, RunResult, RunState
from robot_framework.email import EmailStatus, EmailStep
from robot_framework.registry import Registry
from robot_framework.runner import Runner
from robot_framework.tests import Cancellation, FakeBrowser
from .adapters import DjangoQueue, create_run
from .models import ActionRecord, RobotRun


class EmailPersistenceTests(TestCase):
    def setUp(self):
        project = Project.objects.create(name='Email queue test')
        self.dataset = Dataset.objects.create(project=project, name='Validated rows', source_name='fictional',
            status='ready', schema_snapshot=[{'key':'email'}], headers=['email'], row_count=2)
        self.row = DatasetRow.objects.create(dataset=self.dataset, row_number=2, values={'email':'private@example.invalid'})
        self.next_row = DatasetRow.objects.create(dataset=self.dataset, row_number=3, values={'email':'another@example.invalid'})
        self.run = create_run(self.dataset, 'ROBOT_TEST')
        self.queue = DjangoQueue(self.run)

    def execute(self, status, checkpoint=True):
        spec = EmailStep('notify', 'notifications', '{{email}}', 'Private subject', 'Private body')
        class Robot(BaseRobot):
            email_steps = (spec,)
            def process(self, ctx, inputs):
                if checkpoint:
                    ctx.business_completed()
                ctx.email.send_step(spec, inputs)
        registry, adapter = Registry(), FakeEmailAdapter(status)
        registry.register('test', Robot)
        result = Runner(registry, FakeBrowser([]), None, self.queue, Cancellation(), email=adapter).run(
            'test', [InputRow(str(self.row.pk), self.row.values)], RunOptions(), input_fields={'email'})
        return result, adapter

    def test_business_success_and_notification_failure_both_persist(self):
        result, adapter = self.execute(EmailStatus.FAILED)
        self.assertEqual(result.state, 'failed')
        self.assertEqual(adapter.calls, 1)
        self.row.refresh_from_db()
        self.assertEqual(self.row.processing_status, 'done')
        attempt = self.run.attempts.get()
        self.assertEqual(attempt.outcome, 'ERROR')
        self.assertIsNotNone(attempt.business_completed_at)
        self.assertEqual(attempt.actions.get().status, 'failed')
        replacement = create_run(self.dataset, 'ROBOT_TEST')
        self.assertEqual([row.reference for row in DjangoQueue(replacement).rows()], [str(self.next_row.pk)])
        response = self.client.get(reverse('run-detail', args=[self.run.pk]))
        self.assertContains(response, 'Business operation completed')
        self.assertContains(response, 'Email was not accepted.')
        self.assertNotContains(response, 'private@example.invalid')
        self.assertNotContains(response, 'Private body')

    def test_uncertain_and_simulated_statuses_are_visible(self):
        self.execute(EmailStatus.UNCERTAIN)
        self.assertEqual(ActionRecord.objects.get().status, 'uncertain')
        self.assertContains(self.client.get(reverse('run-detail', args=[self.run.pk])), 'Do not automatically resend')

    def test_failed_email_without_business_checkpoint_preserves_legacy_pending_rule(self):
        self.execute(EmailStatus.FAILED, checkpoint=False)
        self.row.refresh_from_db()
        self.assertEqual(self.row.processing_status, 'pending')
        self.assertIsNone(self.run.attempts.get().business_completed_at)

    def start_interrupted_notification(self):
        self.queue.emit('run_started')
        self.queue.emit('row_started', row=str(self.row.pk))
        self.queue.emit('business_completed', row=str(self.row.pk))
        self.queue.emit('email_started', row=str(self.row.pk), step='notify', action_status='started')

    def test_cancel_after_checkpoint_keeps_done_and_marks_incomplete_email_uncertain(self):
        self.start_interrupted_notification()
        self.queue.emit('run_cancelled', summary=RunResult(state=RunState.CANCELLED))
        self.row.refresh_from_db()
        self.assertEqual(self.row.processing_status, 'done')
        self.assertIsNone(self.row.claimed_by)
        self.assertEqual(ActionRecord.objects.get().status, 'uncertain')
        self.assertIn('Business operation completed', self.run.attempts.get().message)

    def test_lease_recovery_keeps_checkpoint_and_does_not_replay_email(self):
        self.start_interrupted_notification()
        RobotRun.objects.filter(pk=self.run.pk).update(heartbeat=timezone.now() - timedelta(minutes=3))
        replacement = create_run(self.dataset, 'ROBOT_TEST')
        self.row.refresh_from_db()
        self.assertEqual(self.row.processing_status, 'done')
        self.assertIsNone(self.row.claimed_by)
        self.assertEqual(ActionRecord.objects.get().status, 'uncertain')
        self.assertEqual([r.reference for r in DjangoQueue(replacement).rows()], [str(self.next_row.pk)])
