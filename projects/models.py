from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
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
    class Action(models.TextChoices):
        CLICK = 'click', 'Click'
        FILL = 'fill', 'Fill'
        SELECT = 'select', 'Select option'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="steps")
    window = models.ForeignKey("inspector.ApplicationWindow", null=True, blank=True, on_delete=models.PROTECT, related_name="steps")
    position = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    instruction = models.TextField()
    action = models.CharField(max_length=10, choices=Action.choices, blank=True, default='')
    input_column = models.ForeignKey('ProjectInput', null=True, blank=True, on_delete=models.PROTECT, related_name='steps')

    class Meta:
        ordering = ["position", "pk"]
        constraints = [models.UniqueConstraint(fields=["project", "position"], name="unique_project_step_position")]

    def clean(self):
        if self.window_id and self.window.project_id != self.project_id:
            raise ValidationError({"window": "Choose an application from this project."})
        if self.input_column_id and self.input_column.project_id != self.project_id:
            raise ValidationError({'input_column': 'Choose an input from this project.'})
        if self.action in {self.Action.FILL, self.Action.SELECT} and not self.input_column_id:
            raise ValidationError({'input_column': 'Choose the input column whose value this step will use.'})
        if self.input_column_id and self.action not in {self.Action.FILL, self.Action.SELECT}:
            raise ValidationError({'input_column': 'Only Fill and Select option steps use an input column.'})

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


class ProjectInput(Timestamped):
    class DataType(models.TextChoices):
        TEXT = 'text', 'Text'
        NUMBER = 'number', 'Number'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='inputs')
    key = models.CharField(max_length=64, validators=[RegexValidator(r'^[a-z][a-z0-9_]*$', 'Use lowercase letters, numbers and underscores; start with a letter.')])
    description = models.CharField(max_length=300, blank=True)
    data_type = models.CharField(max_length=10, choices=DataType.choices, default=DataType.TEXT)
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ['pk']
        constraints = [models.UniqueConstraint(fields=['project', 'key'], name='unique_project_input_key')]

    def __str__(self):
        return self.key


class Dataset(Timestamped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='datasets')
    name = models.CharField(max_length=200)
    source_name = models.CharField(max_length=255)
    schema_snapshot = models.JSONField()
    headers = models.JSONField()
    status = models.CharField(max_length=10, choices=[('preview', 'Preview'), ('ready', 'Ready')], default='preview')
    row_count = models.PositiveIntegerField(default=0)
    invalid_row_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name


class DatasetRow(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name='rows')
    row_number = models.PositiveIntegerField()
    values = models.JSONField()
    errors = models.JSONField(default=list)
    processing_status = models.CharField(max_length=12, choices=[('pending', 'Pending'), ('in_progress', 'In progress'), ('done', 'Done')], default='pending')
    claimed_by = models.ForeignKey('execution.RobotRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='claimed_rows')

    class Meta:
        ordering = ['row_number']
        constraints = [models.UniqueConstraint(fields=['dataset', 'row_number'], name='unique_dataset_row')]
