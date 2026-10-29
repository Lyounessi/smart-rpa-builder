import uuid
from django.core.exceptions import ValidationError
from django.db import models


class ContextSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey('projects.Project', on_delete=models.PROTECT, related_name='muse_snapshots')
    created_at = models.DateTimeField(auto_now_add=True)
    specification_hash = models.CharField(max_length=64)
    contract_version = models.CharField(max_length=30)
    contract_hash = models.CharField(max_length=64)
    platform_instructions = models.JSONField()
    framework_contract = models.TextField()
    example_robot = models.TextField()
    project_data = models.JSONField()
    images = models.JSONField(default=list)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Context snapshots are immutable. Create a new snapshot.')
        return super().save(*args, **kwargs)


class MuseBudget(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    committed_usd = models.DecimalField(max_digits=16, decimal_places=8, default=0)


class MuseRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(ContextSnapshot, null=True, blank=True, on_delete=models.PROTECT, related_name='requests')
    operation = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    outcome = models.CharField(max_length=20, default='running')
    error_code = models.CharField(max_length=40, blank=True)
    active_slot = models.CharField(max_length=10, null=True, unique=True, default='local')
    max_output_tokens = models.PositiveIntegerField()
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    cached_tokens = models.PositiveIntegerField(null=True, blank=True)
    pricing = models.JSONField()
    reserved_usd = models.DecimalField(max_digits=16, decimal_places=8)
    estimated_cost_usd = models.DecimalField(max_digits=16, decimal_places=8, null=True, blank=True)
    accounted_usd = models.DecimalField(max_digits=16, decimal_places=8)
    usage_known = models.BooleanField(default=False)
    build_operation = models.OneToOneField('BuildOperation', null=True, blank=True, on_delete=models.PROTECT, related_name='request_record')

    class Meta:
        ordering = ['-created_at']


class BuildSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey('projects.Project', on_delete=models.PROTECT, related_name='build_sessions')
    snapshot = models.ForeignKey(ContextSnapshot, on_delete=models.PROTECT, related_name='build_sessions')
    created_at = models.DateTimeField(auto_now_add=True)
    state = models.CharField(max_length=30, default='needs_clarification')
    rounds_used = models.PositiveSmallIntegerField(default=0)
    decisions = models.JSONField(default=dict)
    assumptions = models.JSONField(default=list)
    model_ready = models.BooleanField(default=False)
    manual_reviewed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_specification = models.JSONField(default=dict)
    confirmed_hash = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ['-created_at']


class BuildMessage(models.Model):
    session = models.ForeignKey(BuildSession, on_delete=models.CASCADE, related_name='messages')
    created_at = models.DateTimeField(auto_now_add=True)
    role = models.CharField(max_length=12, choices=[('user','User'), ('assistant','Muse')])
    content = models.TextField()
    raw_response = models.TextField(blank=True)
    structured = models.JSONField(default=dict)
    review_status = models.CharField(max_length=12, default='pending')
    reviewed_at = models.DateTimeField(null=True, blank=True)


class BuildQuestion(models.Model):
    session = models.ForeignKey(BuildSession, on_delete=models.CASCADE, related_name='questions')
    message = models.ForeignKey(BuildMessage, on_delete=models.CASCADE)
    key = models.CharField(max_length=50)
    text = models.CharField(max_length=600)
    choices = models.JSONField(default=list)
    answer = models.CharField(max_length=2000, blank=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['session','key'], name='unique_build_session_question')]


class BuildProposal(models.Model):
    session = models.ForeignKey(BuildSession, on_delete=models.CASCADE, related_name='proposals')
    message = models.ForeignKey(BuildMessage, on_delete=models.CASCADE, related_name='proposals')
    field = models.CharField(max_length=40)
    step_id = models.PositiveIntegerField(null=True, blank=True)
    value = models.TextField()
    reason = models.CharField(max_length=600)
    status = models.CharField(max_length=12, default='pending')


class BuildOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(BuildSession, on_delete=models.PROTECT, related_name='operations')
    created_at = models.DateTimeField(auto_now_add=True)
    heartbeat = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    round_number = models.PositiveSmallIntegerField()
    expected_revision = models.CharField(max_length=64)
    status = models.CharField(max_length=12, default='queued')
    active_slot = models.CharField(max_length=10, null=True, unique=True, default='local')
    include_images = models.BooleanField(default=False)
    error_message = models.CharField(max_length=400, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['session','round_number'], name='unique_session_review_round')]
