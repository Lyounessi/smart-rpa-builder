import uuid
from django.db import models
from projects.models import Timestamped


class Robot(Timestamped):
    project = models.OneToOneField('projects.Project', on_delete=models.PROTECT, related_name='robot')
    name = models.CharField(max_length=240)

    def __str__(self):
        return self.name


class RobotBuild(Timestamped):
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT, related_name='builds')
    version = models.PositiveIntegerField()
    origin = models.CharField(max_length=10, choices=[('manual', 'Manual'), ('muse', 'Muse')])
    status = models.CharField(max_length=20, choices=[('registered', 'Registered'), ('queued', 'Queued'),
        ('building', 'Building'), ('validated', 'Validated'), ('failed', 'Failed')])
    source_files = models.JSONField(default=dict)
    configuration = models.JSONField(default=dict)
    source_digest = models.CharField(max_length=64, blank=True)
    validation_report = models.JSONField(default=list)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['robot', 'version'], name='unique_robot_build_version')]

    def __str__(self):
        return f'{self.robot.name} v{self.version}'


class RobotRun(Timestamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset = models.ForeignKey('projects.Dataset', on_delete=models.PROTECT, related_name='runs')
    robot_name = models.CharField(max_length=240)
    build = models.ForeignKey(RobotBuild, null=True, blank=True, on_delete=models.PROTECT, related_name='runs')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
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
    business_completed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'row'], name='unique_run_row_attempt')]


class ProgressEvent(models.Model):
    run = models.ForeignKey(RobotRun, on_delete=models.CASCADE, related_name='events')
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=40)
    row_reference = models.CharField(max_length=40, blank=True)
    step = models.CharField(max_length=200, blank=True)


class ActionRecord(Timestamped):
    attempt = models.ForeignKey(RowAttempt, on_delete=models.CASCADE, related_name='actions')
    step_id = models.CharField(max_length=200)
    action_type = models.CharField(max_length=30, default='send_email')
    status = models.CharField(max_length=12, choices=[(value, value.title()) for value in
        ['started', 'simulated', 'accepted', 'failed', 'uncertain']])
    message = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'step_id'], name='unique_attempt_action_step')]
