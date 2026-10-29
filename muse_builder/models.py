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

    class Meta:
        ordering = ['-created_at']
