"""Short database transactions around queue transitions, never browser operations."""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from threading import Event, Thread

from django.db import close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from projects.models import DatasetRow
from robot_framework.contracts import ExecutionCancelled, InputRow
from .models import ActionRecord, ProgressEvent, RobotRun, RowAttempt

LEASE_SECONDS = 120

EMAIL_MESSAGES = {
    'started': 'Email attempt started.',
    'simulated': 'Email simulated; no message sent.',
    'accepted': 'Email accepted by provider; inbox delivery not confirmed.',
    'failed': 'Email was not accepted.',
    'uncertain': 'Email delivery uncertain. Do not automatically resend.',
}


def release_claims(run, recovered=False):
    if not recovered:
        RowAttempt.objects.filter(run=run, finished_at__isnull=True).update(finished_at=timezone.now())
    DatasetRow.objects.filter(claimed_by=run, processing_status='in_progress').update(processing_status='pending')
    DatasetRow.objects.filter(claimed_by=run).update(claimed_by=None)
    RowAttempt.objects.filter(run=run, outcome='', business_completed_at__isnull=True).update(message='Interrupted before outcome was confirmed.')
    RowAttempt.objects.filter(run=run, outcome='', business_completed_at__isnull=False).update(message='Business operation completed; remaining steps interrupted.')
    ActionRecord.objects.filter(attempt__run=run, status='started').update(status='uncertain', message=EMAIL_MESSAGES['uncertain'], updated_at=timezone.now())


@transaction.atomic
def create_run(dataset, name, build=None):
    # The unique active slot is authoritative even when two command processes race.
    for stale in RobotRun.objects.filter(active_slot='local', heartbeat__lt=timezone.now() - timedelta(seconds=LEASE_SECONDS)):
        release_claims(stale, recovered=True)
        stale.state, stale.active_slot, stale.message = 'failed', None, 'Worker lease expired. Check external effects before retrying.'
        stale.save(update_fields=['state', 'active_slot', 'message'])
    if dataset.status != 'ready' or dataset.rows.exclude(errors=[]).exists():
        raise ValueError('Choose a confirmed, valid dataset.')
    if not dataset.rows.filter(processing_status='pending', errors=[]).exists():
        raise ValueError('No pending rows remain in this dataset.')
    if build is not None and (build.robot.project_id != dataset.project_id or build.configuration.get('robot_name') != name):
        raise ValueError('Build does not belong to this project and robot.')
    return RobotRun.objects.create(dataset=dataset, robot_name=name, build=build, heartbeat=timezone.now())


class DjangoQueue:
    def __init__(self, run):
        self.run = run
        self.selected_rows = {}

    def rows(self):
        rows = self.run.dataset.rows.filter(processing_status='pending', errors=[])
        if self.run.is_test:
            rows = rows[:self.run.test_options['row_limit']]
        selected = [InputRow(str(row.pk), row.values) for row in rows]
        self.selected_rows = {item.reference:item for item in selected}
        return selected

    def emit(self, kind, row=None, step=None, result=None, summary=None, action_status=None):
        with transaction.atomic():
            # Serialize queue transitions against manual edits and heartbeats.
            # SQLite cannot safely upgrade an earlier read snapshot to a writer.
            if RobotRun.objects.filter(pk=self.run.pk,active_slot='local').update(heartbeat=F('heartbeat')) != 1:
                raise ExecutionCancelled()
            current = RobotRun.objects.get(pk=self.run.pk)
            if current.active_slot != 'local':
                raise ExecutionCancelled()
            if kind == 'run_started':
                current.state = 'running'
                current.started_at = current.started_at or timezone.now()
                current.save(update_fields=['state', 'started_at'])
            elif kind == 'row_started':
                if current.cancel_requested:
                    raise ExecutionCancelled()
                claimed = DatasetRow.objects.filter(pk=row, dataset=current.dataset, processing_status='pending').update(processing_status='in_progress', claimed_by=current)
                if claimed != 1:
                    raise RuntimeError('Row is no longer available.')
                values = DatasetRow.objects.get(pk=row,dataset=current.dataset).values
                selected = self.selected_rows.get(str(row))
                if selected is not None:
                    selected.values.clear()
                    selected.values.update(deepcopy(values))
                RowAttempt.objects.create(run=current, row_id=row, started_at=timezone.now(),input_snapshot=deepcopy(values))
            elif kind == 'row_finished':
                attempt = RowAttempt.objects.get(run=current, row_id=row)
                business_done = attempt.business_completed_at is not None or result.status == 'OK'
                RowAttempt.objects.filter(pk=attempt.pk).update(outcome=result.status, message=result.message,
                    failed_step=result.failed_step or '', evidence=result.evidence, outputs=result.outputs, updated_at=timezone.now(), finished_at=timezone.now())
                if business_done and attempt.business_completed_at is None:
                    RowAttempt.objects.filter(pk=attempt.pk).update(business_completed_at=timezone.now())
                DatasetRow.objects.filter(pk=row, claimed_by=current).update(
                    processing_status='done' if business_done else 'pending', claimed_by=None)
            elif kind == 'business_completed':
                attempt = RowAttempt.objects.get(run=current, row_id=row)
                if result is not None:
                    RowAttempt.objects.filter(pk=attempt.pk).update(outputs=result.outputs)
                if DatasetRow.objects.filter(pk=row, claimed_by=current).update(processing_status='done') != 1:
                    raise RuntimeError('Business completion requires a claimed row.')
                if attempt.business_completed_at is None:
                    RowAttempt.objects.filter(pk=attempt.pk).update(business_completed_at=timezone.now())
            elif kind in {'email_started', 'email_finished'}:
                attempt = RowAttempt.objects.get(run=current, row_id=row)
                if action_status not in EMAIL_MESSAGES or not step:
                    raise ValueError('Invalid email action event.')
                if kind == 'email_started':
                    ActionRecord.objects.create(attempt=attempt, step_id=step, status='started', message=EMAIL_MESSAGES['started'])
                else:
                    if action_status == 'started' or ActionRecord.objects.filter(attempt=attempt, step_id=step, status='started').update(
                            status=action_status, message=EMAIL_MESSAGES[action_status], updated_at=timezone.now()) != 1:
                        raise ValueError('Email action was not started or was already finalized.')
            if summary is not None:
                release_claims(current)
                current.state, current.message, current.active_slot = summary.state, summary.message, None
                current.counts = dict(Counter(item.status for item in summary.rows))
                current.cleanup_errors, current.artifacts = summary.cleanup_errors, summary.artifacts
                current.unprocessed = summary.unprocessed
                current.finished_at = timezone.now()
                current.save()
            ProgressEvent.objects.create(run=current, kind=kind, row_reference=row or '', step=step or '')


class LeaseCancellation:
    def __init__(self, run_id):
        self.run_id = run_id
        self.stop = Event()
        self.lost = Event()
        self.thread = Thread(target=self._heartbeat, daemon=True)

    def _heartbeat(self):
        close_old_connections()
        try:
            while not self.stop.wait(5):
                try:
                    if RobotRun.objects.filter(pk=self.run_id, active_slot='local').update(heartbeat=timezone.now()) != 1:
                        self.lost.set()
                        return
                except Exception:
                    self.lost.set()
                    return
        finally:
            close_old_connections()

    def requested(self):
        return self.lost.is_set() or not RobotRun.objects.filter(pk=self.run_id, active_slot='local', cancel_requested=False).exists()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=6)
