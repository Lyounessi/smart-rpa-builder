from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Project, WorkflowStep


@transaction.atomic
def save_new_step(form, project):
    Project.objects.select_for_update().get(pk=project.pk)
    last = project.steps.aggregate(last=Max("position"))["last"] or 0
    form.instance.position = last + 1
    return form.save()


@transaction.atomic
def move_step(step, direction):
    Project.objects.select_for_update().get(pk=step.project_id)
    steps = list(WorkflowStep.objects.filter(project_id=step.project_id))
    index = next(i for i, item in enumerate(steps) if item.pk == step.pk)
    destination = index + (-1 if direction == "up" else 1)
    if not 0 <= destination < len(steps):
        return
    other = steps[destination]
    old_position = steps[index].position
    WorkflowStep.objects.filter(pk=step.pk).update(position=max(item.position for item in steps) + 1)
    changed_at = timezone.now()
    WorkflowStep.objects.filter(pk=other.pk).update(position=old_position, updated_at=changed_at)
    WorkflowStep.objects.filter(pk=step.pk).update(position=other.position, updated_at=changed_at)
