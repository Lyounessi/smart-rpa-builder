import subprocess
import sys
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from projects.models import StepElementReference, WorkflowStep
from .models import CaptureDraft, CapturedElement, InspectionCommand, InspectionSession

SERVER_INSTANCE = str(uuid.uuid4())


def reconcile_sessions():
    stale = timezone.now() - timedelta(seconds=30)
    for session in InspectionSession.objects.filter(active_slot="local", heartbeat__lt=stale):
        finish_session(session.pk, 'interrupted', 'Browser worker stopped responding. Start a new session.')
    for session in InspectionSession.objects.filter(active_slot="local").exclude(server_instance=SERVER_INSTANCE):
        finish_session(session.pk, 'interrupted', 'The server restarted. Reopen the browser; saved targets are unchanged.')


def start_session(step, server_url):
    reconcile_sessions()
    if not step.window_id or step.window.application_type != "web" or step.window.project_id != step.project_id:
        raise ValidationError("Save this step with a web target application first.")
    current = InspectionSession.objects.filter(active_slot="local").first()
    if current:
        if current.step_id == step.pk:
            raise ValidationError("An inspector is already running for this step. Use its controls below.")
        if current.project_id == step.project_id and current.window_id == step.window_id:
            if current.status != 'browsing' or current.commands.filter(status__in=['pending', 'running']).exists():
                raise ValidationError("Finish or cancel the current operation before switching steps.")
            current.step = step
            current.message = "Browser reused for this step. Select the next target."
            current.save(update_fields=['step', 'message', 'updated_at'])
            return current
        raise ValidationError("An inspector is already running. Open its step and stop it before launching another.")
    try:
        with transaction.atomic():
            session = InspectionSession.objects.create(project=step.project, window=step.window, step=step,
                server_instance=SERVER_INSTANCE, heartbeat=timezone.now())
    except IntegrityError:
        raise ValidationError("An inspector is already running. Open its step and stop it before launching another.")
    try:
        subprocess.Popen([sys.executable, str(settings.BASE_DIR / "manage.py"), "inspect_browser", str(session.pk),
                          "--server-url", server_url], cwd=settings.BASE_DIR,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except OSError:
        finish_session(session.pk, "error", "Could not start the browser worker. Check the Python installation.")
    return session


def finish_session(session_id, status="stopped", message="Inspector stopped. Browser closed."):
    InspectionSession.objects.filter(pk=session_id).update(status=status, active_slot=None, message=message, heartbeat=timezone.now())
    InspectionCommand.objects.filter(session_id=session_id, status__in=["pending", "running"]).update(status="failed", result={"message": message})


@transaction.atomic
def enqueue(session, operation, element=None):
    current = InspectionSession.objects.select_for_update().get(pk=session.pk)
    if current.active_slot is None or (current.status == "starting" and operation != "stop"):
        raise ValidationError("Wait for the browser to open, or start a new session.")
    if operation not in {"select", "cancel", "test", "stop"}:
        raise ValidationError("Unsupported inspector operation.")
    if element and (element.window_id != current.window_id or operation != "test"):
        raise ValidationError("Choose a target from this application's window.")
    if operation == "test" and element is None:
        raise ValidationError("Choose a saved target to test.")
    if operation != "stop" and (current.status in {"selecting", "capturing", "testing"} or current.commands.filter(status__in=["pending", "running"]).exists()):
        if operation != "cancel":
            raise ValidationError("Finish or cancel the current operation first.")
    return InspectionCommand.objects.create(session=current, operation=operation, element=element)


def discard_draft(draft):
    draft.highlighted_screenshot.delete(save=False)
    draft.element_screenshot.delete(save=False)
    draft.delete()


@transaction.atomic
def save_draft(draft_id, session, name, description):
    draft = CaptureDraft.objects.select_for_update().get(pk=draft_id, session=session, status="review")
    step = WorkflowStep.objects.select_for_update().get(pk=draft.step_id or session.step_id)
    if step.project_id != session.project_id or step.window_id != session.window_id:
        raise ValidationError("This step's application changed. Capture a new target for its current application.")
    element = CapturedElement(window=session.window, name=name, description=description,
        element_type=draft.metadata.get("tag", ""), semantic_metadata=draft.metadata, locator=draft.locator,
        selector_quality=draft.selector_quality,
        validation_result=draft.validation_result, validated_at=draft.created_at,
        capture_url=draft.capture_url, coordinate_context=draft.coordinate_context)
    # Transfer file references: no additional screenshot copies or raw images are created.
    element.highlighted_screenshot.name = draft.highlighted_screenshot.name
    element.element_screenshot.name = draft.element_screenshot.name
    element.save()
    step.element_references.all().delete()
    StepElementReference.objects.create(step=step, element=element)
    draft.status = "saved"
    draft.save(update_fields=["status", "updated_at"])
    return element


def persist_draft(session_id, metadata, locator, validation, capture_url, coordinates, viewport, crop, step_id=None, selector_quality=None):
    # A recapture replaces only the unsaved review, never the step's saved target.
    step_id = step_id or InspectionSession.objects.values_list('step_id', flat=True).get(pk=session_id)
    for old in CaptureDraft.objects.filter(step_id=step_id, status="review"):
        discard_draft(old)
    draft = CaptureDraft(session_id=session_id, step_id=step_id, metadata=metadata, locator=locator,
        selector_quality=selector_quality or {},
        validation_result=validation, capture_url=capture_url, coordinate_context=coordinates)
    try:
        draft.highlighted_screenshot.save(f"{draft.pk}-viewport.png", ContentFile(viewport), save=False)
        draft.element_screenshot.save(f"{draft.pk}-element.png", ContentFile(crop), save=False)
        draft.save()
    except Exception:
        draft.highlighted_screenshot.delete(save=False)
        draft.element_screenshot.delete(save=False)
        raise
    return str(draft.pk)
