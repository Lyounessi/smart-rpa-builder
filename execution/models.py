import uuid
from django.db import models
from projects.models import Timestamped


class RobotRun(Timestamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey('projects.Dataset', on_delete=models.PROTECT, related_name='runs')
    robot_name = models.CharField(max_length=240)
    state = models.CharField(max_length=12, default='queued')
    active_slot = models.CharField(max_length=10, null=True, unique=True, default='local')
    heartbeat = models.DateTimeField()
    cancel_requested = models.BooleanField(default=False)
    counts = models.JSONField(default=dict)
    message = models.CharField(max_length=300, blank=True)
    cleanup_errors = models.JSONField(default=list)
    artifacts = models.JSONField(default=list)
    unprocessed = models.JSONField(default=list)


class RowAttempt(Timestamped):
    run = models.ForeignKey(RobotRun, on_delete=models.CASCADE, related_name='attempts')
    row = models.ForeignKey('projects.DatasetRow', on_delete=models.PROTECT)
    outcome = models.CharField(max_length=10, blank=True)
    message = models.CharField(max_length=300, blank=True)
    failed_step = models.CharField(max_length=200, blank=True)
    evidence = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'row'], name='unique_run_row_attempt')]


class ProgressEvent(models.Model):
    run = models.ForeignKey(RobotRun, on_delete=models.CASCADE, related_name='events')
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=40)
    row_reference = models.CharField(max_length=40, blank=True)
    step = models.CharField(max_length=200, blank=True)
