import uuid

from django.db import models

from projects.models import Timestamped


class ApplicationWindow(Timestamped):
    class ApplicationType(models.TextChoices):
        WEB = "web", "Web"
        DESKTOP = "desktop", "Desktop (future)"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="windows")
    name = models.CharField(max_length=200)
    application_type = models.CharField(max_length=10, choices=ApplicationType.choices, default=ApplicationType.WEB)
    target_url = models.URLField(max_length=2048, blank=True)
    identification_metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


class CapturedElement(Timestamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    window = models.ForeignKey(ApplicationWindow, on_delete=models.CASCADE, related_name="elements")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    element_type = models.CharField(max_length=100, blank=True)
    semantic_metadata = models.JSONField(default=dict, blank=True)
    locator = models.JSONField(default=dict)
    locator_version = models.PositiveSmallIntegerField(default=1)
    selector_quality = models.JSONField(default=dict, blank=True)
    validation_result = models.JSONField(default=dict, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    capture_url = models.URLField(max_length=2048, blank=True)
    frame_context = models.JSONField(default=dict, blank=True)
    highlighted_screenshot = models.FileField(upload_to="captures/%Y/%m/%d/", blank=True)
    element_screenshot = models.FileField(upload_to="captures/%Y/%m/%d/", blank=True)
    coordinate_context = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


class InspectionSession(Timestamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    window = models.ForeignKey(ApplicationWindow, on_delete=models.CASCADE)
    step = models.ForeignKey("projects.WorkflowStep", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default="starting")
    # Nullable unique slot enforces one live local browser, including concurrent launches.
    active_slot = models.CharField(max_length=20, null=True, default="local", unique=True)
    server_instance = models.CharField(max_length=36)
    heartbeat = models.DateTimeField(null=True)
    message = models.CharField(max_length=300, blank=True)


class InspectionCommand(Timestamped):
    session = models.ForeignKey(InspectionSession, on_delete=models.CASCADE, related_name="commands")
    operation = models.CharField(max_length=20)
    element = models.ForeignKey(CapturedElement, null=True, blank=True, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default="pending")
    result = models.JSONField(default=dict, blank=True)


class CaptureDraft(Timestamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(InspectionSession, on_delete=models.CASCADE, related_name="drafts")
    step = models.ForeignKey("projects.WorkflowStep", null=True, on_delete=models.CASCADE, related_name="capture_drafts")
    status = models.CharField(max_length=20, default="review")
    metadata = models.JSONField(default=dict)
    locator = models.JSONField(default=dict)
    selector_quality = models.JSONField(default=dict, blank=True)
    validation_result = models.JSONField(default=dict)
    capture_url = models.URLField(max_length=2048, blank=True)
    coordinate_context = models.JSONField(default=dict)
    highlighted_screenshot = models.FileField(upload_to="drafts/%Y/%m/%d/")
    element_screenshot = models.FileField(upload_to="drafts/%Y/%m/%d/")
