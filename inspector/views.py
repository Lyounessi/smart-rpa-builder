from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from projects.models import WorkflowStep
from .forms import CaptureReviewForm
from .models import CaptureDraft, CapturedElement, InspectionSession
from .services import SERVER_INSTANCE, discard_draft, enqueue, reconcile_sessions, save_draft, start_session


def get_step(project_id, step_id):
    return get_object_or_404(WorkflowStep.objects.select_related('project', 'window'), pk=step_id, project_id=project_id)


def workspace(request, step, error='', form=None):
    reconcile_sessions()
    session = InspectionSession.objects.filter(step=step).order_by('-created_at').first()
    draft = step.capture_drafts.filter(status='review').order_by('-created_at').first()
    references = step.element_references.select_related('element').all()
    template = 'inspector/_workspace.html' if request.headers.get('HX-Request') == 'true' else 'inspector/workspace.html'
    return render(request, template, {
        'project':step.project, 'step':step, 'session':session, 'draft':draft,
        'other_session':InspectionSession.objects.filter(active_slot='local').exclude(step=step).first(),
        'references':references, 'error':error,
        'review_form':form or CaptureReviewForm(initial={'name':draft.metadata.get('name') or draft.metadata.get('nearby_label') or draft.metadata.get('tag', '')} if draft else {}),
        'can_select':session and session.active_slot and session.status == 'browsing',
    })


@require_GET
def step_inspector(request, project_id, step_id):
    return workspace(request, get_step(project_id, step_id))


@require_POST
def launch(request, project_id, step_id):
    step = get_step(project_id, step_id)
    try:
        start_session(step, request.build_absolute_uri('/').rstrip('/'))
    except ValidationError as error:
        return workspace(request, step, ' '.join(error.messages))
    return redirect('step-inspector', project_id=project_id, step_id=step_id)


@require_POST
def command(request, project_id, step_id, session_id):
    step = get_step(project_id, step_id)
    session = get_object_or_404(InspectionSession, pk=session_id, step=step, project_id=project_id)
    element = None
    if request.POST.get('element'):
        element = get_object_or_404(CapturedElement, pk=request.POST['element'], window=session.window)
    try:
        enqueue(session, request.POST.get('operation'), element)
    except ValidationError as error:
        return workspace(request, step, ' '.join(error.messages))
    return workspace(request, step)


@require_POST
def review(request, project_id, step_id, draft_id):
    step = get_step(project_id, step_id)
    draft = get_object_or_404(CaptureDraft.objects.select_related('session__window'), pk=draft_id, step=step, status='review')
    if request.POST.get('action') == 'discard':
        discard_draft(draft)
        return redirect('step-inspector', project_id=project_id, step_id=step_id)
    form = CaptureReviewForm(request.POST)
    if form.is_valid():
        try:
            save_draft(draft.pk, draft.session, **form.cleaned_data)
        except ValidationError as error:
            return workspace(request, step, ' '.join(error.messages), form)
        return redirect('step-inspector', project_id=project_id, step_id=step_id)
    return workspace(request, step, form=form)


@require_GET
def health(request, session_id):
    session = get_object_or_404(InspectionSession, pk=session_id, active_slot='local', server_instance=SERVER_INSTANCE)
    return JsonResponse({'instance':session.server_instance})


@require_GET
def screenshot(request, project_id, step_id, capture_id, kind, source):
    step = get_step(project_id, step_id)
    if source == 'draft':
        capture = get_object_or_404(CaptureDraft, pk=capture_id, step=step, status='review')
    elif source == 'saved':
        capture = get_object_or_404(CapturedElement, pk=capture_id, step_references__step=step)
    else:
        raise Http404
    field = {'viewport':capture.highlighted_screenshot, 'element':capture.element_screenshot}.get(kind)
    if not field:
        raise Http404
    try:
        response = FileResponse(field.open('rb'), content_type='image/png')
    except FileNotFoundError:
        raise Http404
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
