from datetime import timedelta
import os
from pathlib import Path
import tempfile
from threading import Thread
from http.server import ThreadingHTTPServer
from unittest import skipUnless

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from projects.models import Dataset, DatasetRow, Project
from robot_framework.contracts import RowResult, RunResult, Outcome, RunState
from .adapters import DjangoQueue, create_run
from .models import RobotRun


class QueueTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Queue')
        self.dataset = Dataset.objects.create(project=self.project, name='Rows', source_name='fixture',
            status='ready', schema_snapshot=[], headers=['name'], row_count=2)
        self.rows = [DatasetRow.objects.create(dataset=self.dataset, row_number=index, values={'name':'private'}) for index in [2, 3]]

    def test_claim_finish_and_progress_page(self):
        run = create_run(self.dataset, 'ROBOT_QUEUE')
        queue = DjangoQueue(run)
        queue.emit('run_started')
        queue.emit('row_started', row=str(self.rows[0].pk))
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].processing_status, 'in_progress')
        self.assertEqual(self.rows[0].claimed_by, run)
        outcome = RowResult(str(self.rows[0].pk), Outcome.OK, 'Verified')
        queue.emit('row_finished', row=outcome.reference, result=outcome)
        queue.emit('run_completed', summary=RunResult(state=RunState.COMPLETED, rows=[outcome], unprocessed=[str(self.rows[1].pk)]))
        run.refresh_from_db()
        self.assertEqual(run.counts, {'OK':1})
        self.assertIsNone(run.active_slot)
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].processing_status, 'done')
        response = self.client.get(reverse('run-detail', args=[run.pk]))
        self.assertContains(response, 'Verified')
        self.assertNotContains(response, 'private')
        self.assertContains(self.client.get(reverse('dataset-detail', args=[self.project.pk, self.dataset.pk])), 'ROBOT_QUEUE')

    def test_error_and_cancel_return_row_to_pending_without_losing_attempt(self):
        for status in [Outcome.ERROR, Outcome.NOK]:
            run = create_run(self.dataset, 'ROBOT_QUEUE')
            queue = DjangoQueue(run)
            row = str(self.rows[0].pk)
            queue.emit('row_started', row=row)
            outcome = RowResult(row, status, 'Safe diagnostic', 'submit')
            queue.emit('row_finished', row=row, result=outcome)
            queue.emit('run_completed', summary=RunResult(state=RunState.COMPLETED, rows=[outcome]))
            self.rows[0].refresh_from_db()
            self.assertEqual(self.rows[0].processing_status, 'pending')
            self.assertEqual(run.attempts.get().outcome, status)
        run = create_run(self.dataset, 'ROBOT_QUEUE')
        queue = DjangoQueue(run)
        queue.emit('row_started', row=str(self.rows[0].pk))
        self.client.post(reverse('run-cancel', args=[run.pk]))
        queue.emit('run_cancelled', summary=RunResult(state=RunState.CANCELLED))
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].processing_status, 'pending')
        self.assertEqual(run.attempts.get().outcome, '')

    def test_active_slot_and_expired_lease(self):
        run = create_run(self.dataset, 'ROBOT_QUEUE')
        queue = DjangoQueue(run)
        queue.emit('row_started', row=str(self.rows[0].pk))
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_run(self.dataset, 'ROBOT_QUEUE')
        RobotRun.objects.filter(pk=run.pk).update(heartbeat=timezone.now() - timedelta(minutes=3))
        replacement = create_run(self.dataset, 'ROBOT_QUEUE')
        run.refresh_from_db()
        self.assertEqual(run.state, 'failed')
        self.assertIsNone(run.active_slot)
        self.assertNotEqual(replacement.pk, run.pk)
        self.rows[0].refresh_from_db()
        self.assertEqual(self.rows[0].processing_status, 'pending')

    def test_preview_and_invalid_dataset_rejected(self):
        self.dataset.status = 'preview'
        with self.assertRaises(ValueError):
            create_run(self.dataset, 'ROBOT_QUEUE')


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'Opt-in real Chromium smoke test')
class BrowserRobotTests(TransactionTestCase):
    def test_two_rows_recording_and_cleanup(self):
        self.run_browser_fixture(with_email=False)

    def test_email_steps_simulated_without_targets_or_network(self):
        self.run_browser_fixture(with_email=True)

    def run_browser_fixture(self, with_email):
        from unittest.mock import patch
        from .management.commands.serve_robot_fixture import Handler

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server, tempfile.TemporaryDirectory() as artifacts:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                call_command('prepare_robot_demo', port=server.server_port, with_email=with_email)
                name = 'Invoice Checks Email' if with_email else 'Invoice Checks'
                dataset = Dataset.objects.get(project__name=name)
                with override_settings(MEDIA_ROOT=artifacts), patch.dict(os.environ, {'RPA_SECRET_DEMO_USERNAME':'demo', 'RPA_SECRET_DEMO_PASSWORD':'demo'}):
                    call_command('run_robot', 'ROBOT_INVOICE_CHECKS_EMAIL' if with_email else 'ROBOT_INVOICE_CHECKS',
                                 dataset=dataset.pk, record_screen=True, fake_email=with_email)
                run = RobotRun.objects.get(dataset=dataset)
                self.assertEqual(run.state, 'completed', run.message)
                self.assertEqual(list(run.attempts.order_by('pk').values_list('outcome', flat=True)), ['OK', 'OK'])
                self.assertTrue(run.artifacts)
                self.assertTrue(all(Path(path).stat().st_size > 0 for path in run.artifacts))
                self.assertEqual(dataset.rows.filter(processing_status='done').count(), 2)
                run.refresh_from_db()
                self.assertIsNone(run.active_slot)
                if with_email:
                    from .models import ActionRecord
                    self.assertEqual(list(ActionRecord.objects.filter(attempt__run=run).values_list('status', flat=True)), ['simulated', 'simulated'])
                    self.assertEqual(run.attempts.filter(business_completed_at__isnull=False).count(), 2)
            finally:
                server.shutdown()
                thread.join(timeout=3)
