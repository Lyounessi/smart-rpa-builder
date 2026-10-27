from django.core.exceptions import ValidationError
from django.db import models


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Project(Timestamped):
    class ApplicationScope(models.TextChoices):
        WEB = "web", "Web application"
        DESKTOP = "desktop", "Desktop application"
        MULTIPLE = "multiple", "Multiple applications"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    application_scope = models.CharField(max_length=10, choices=ApplicationScope.choices, default=ApplicationScope.WEB)

    def __str__(self):
        return self.name


class WorkflowStep(Timestamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="steps")
    window = models.ForeignKey("inspector.ApplicationWindow", null=True, blank=True, on_delete=models.PROTECT, related_name="steps")
    position = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    instruction = models.TextField()

    class Meta:
        ordering = ["position", "pk"]
        constraints = [models.UniqueConstraint(fields=["project", "position"], name="unique_project_step_position")]

    def clean(self):
        if self.window_id and self.window.project_id != self.project_id:
            raise ValidationError({"window": "Choose an application from this project."})

    def __str__(self):
        return self.name


class StepElementReference(Timestamped):
    step = models.ForeignKey(WorkflowStep, on_delete=models.CASCADE, related_name="element_references")
    element = models.ForeignKey("inspector.CapturedElement", on_delete=models.PROTECT, related_name="step_references")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["step", "element"], name="unique_step_element")]

    def clean(self):
        if self.step_id and self.element_id:
            if self.step.project_id != self.element.window.project_id:
                raise ValidationError("The element must belong to the step's project.")
            if self.step.window_id and self.step.window_id != self.element.window_id:
                raise ValidationError("The element must belong to the step's application.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
