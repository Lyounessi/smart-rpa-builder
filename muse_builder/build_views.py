from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from projects.models import Project
from .client import MetaConfiguration, MuseError
from .budget import SpendingPolicy
from .conversation import (MAX_ROUNDS, confirm_specification, launch, local_issues, queue_review,
                           review_proposals, revision, save_decisions, start_session)
from .conversation import refresh_specification
from .context import require_current
from .forms import ReplyForm, SpecificationForm, decision_form_data
from .models import BuildSession, MuseBudget

FIELD_LABELS = {'setup_step_ids':'Setup steps', 'per_row_step_ids':'Per-row steps', 'finalization_step_ids':'Final checks', 'stop_on_nok':'Business rejection policy',
    'unsupported_request_resolution':'Resolution of capability warnings',
    'stop_on_error':'Technical error policy','success_criteria':'Success criteria','rejection_handling':'Known rejection handling',
    'recovery_plan':'Recovery plan','automation_goal':'Goal','global_rules':'Global rules','brief_success_criteria':'Brief success criteria',
    'step_instruction':'Step instruction','step_input_mapping':'Input mapping','step_target':'Captured target'}


def get_session(project, session_id):
    try:
        return get_object_or_404(BuildSession.objects.select_related('snapshot','project'), pk=session_id, project=project)
    except (ValidationError, ValueError):
        raise Http404 from None


def workspace(request, project, session=None, *, error='', reply_form=None, specification_form=None):
    active = session.operations.filter(active_slot='local').first() if session else None
    stale = False
    if session:
        try:
            require_current(session.snapshot)
        except MuseError:
            stale = True
    template = 'muse_builder/_build_workspace.html' if request.headers.get('HX-Request') == 'true' else 'muse_builder/build.html'
    latest = session.messages.filter(role='assistant').last() if session else None
    service_block = ''
    if not active:
        try:
            configuration = MetaConfiguration.from_settings()
            policy = SpendingPolicy.load(configuration.model)
            budget = MuseBudget.objects.filter(pk=1).first()
            if policy.output_cap < 1536:
                service_block = 'Clarification requires an output cap of at least 1536 tokens. Adjust the backend setting or edit decisions locally.'
            elif (budget.committed_usd if budget else 0) + policy.reservation(1536) > policy.limit:
                service_block = 'The local spending limit blocks another review. You can still edit and confirm the specification locally.'
        except MuseError as blocked:
            service_block = blocked.message
    can_review = session is not None and not active and not stale and session.rounds_used < MAX_ROUNDS and not session.proposals.filter(status='pending').exists()
    can_review = can_review and not service_block
    messages = list(session.messages.prefetch_related('proposals').order_by('pk')) if session else []
    step_names = {item['id']:item['name'] for item in session.snapshot.project_data['steps']} if session else {}
    for message in messages:
        for proposal in message.proposals.all():
            proposal.display_label = FIELD_LABELS[proposal.field]
            proposal.step_name = step_names.get(proposal.step_id, '')
    decision_summary = []
    if session:
        for key,value in session.decisions.items():
            if key.endswith('_step_ids'):
                value = ', '.join(step_names.get(pk,str(pk)) for pk in value) or 'None'
            elif isinstance(value,bool):
                value = 'Stop' if value else 'Continue after recovery'
            decision_summary.append({'label':FIELD_LABELS.get(key,key),'value':value or 'Not specified'})
    return render(request, template, {'project':project,'session':session,'active':active,'stale':stale,'error':error,
        'worker_stale':bool(active and active.heartbeat < timezone.now() - timedelta(minutes=5)),
        'latest':latest,'history':project.build_sessions.all()[:15],
        'session_revision':revision(session) if session else '',
        'messages':messages,'decision_summary':decision_summary,'service_block':service_block,
        'questions':session.questions.filter(resolved=False).order_by('pk') if session else [],
        'issues':local_issues(session) if session else [], 'can_review':can_review,
        'reply_form':reply_form or (ReplyForm(session=session) if session else None),
        'specification_form':specification_form or (SpecificationForm(initial=decision_form_data(session.decisions), project=project) if session else None)})


@require_GET
def detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    session = get_session(project, request.GET['session']) if request.GET.get('session') else project.build_sessions.select_related('snapshot','project').first()
    return workspace(request, project, session)


def back(project, session):
    return redirect(reverse('muse-build', args=[project.pk]) + '?session=' + str(session.pk))


@require_POST
def start(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    try:
        session = start_session(project)
    except MuseError as error:
        return workspace(request, project, project.build_sessions.first(), error=error.message)
    return back(project, session)


@require_POST
def refresh(request, project_id, session_id):
    project = get_object_or_404(Project, pk=project_id)
    session = get_session(project, session_id)
    try:
        current = refresh_specification(session)
    except MuseError as error:
        return workspace(request,project,session,error=error.message)
    return back(project,current)


@require_POST
def reply(request, project_id, session_id):
    project = get_object_or_404(Project, pk=project_id)
    session = get_session(project, session_id)
    form = ReplyForm(request.POST, session=session)
    if form.is_valid():
        answers = {question.pk:form.cleaned_data.get(f'question_{question.pk}', '')
                   for question in session.questions.filter(resolved=False)}
        parts = [f'{question.key}: {answers[question.pk]}' for question in session.questions.filter(resolved=False) if answers[question.pk]]
        if form.cleaned_data['message']:
            parts.append(form.cleaned_data['message'])
        if parts:
            try:
                operation = queue_review(session, content='\n'.join(parts), answers=answers, include_images=form.cleaned_data['include_images'], expected_revision=request.POST.get('revision',''))
            except MuseError as error:
                return workspace(request, project, session, error=error.message, reply_form=form)
            launch(operation)
            return back(project, session)
        form.add_error('message', 'Provide an answer or workflow context before requesting another paid review.')
    return workspace(request, project, session, reply_form=form)


@require_POST
def proposals(request, project_id, session_id, message_id):
    project = get_object_or_404(Project, pk=project_id)
    session = get_session(project, session_id)
    get_object_or_404(session.messages, pk=message_id, role='assistant', review_status='pending')
    if request.POST.get('decision') not in {'confirm','reject'}:
        return workspace(request, project, session, error='Choose confirm or reject.')
    try:
        session = review_proposals(session, message_id, accept=request.POST['decision'] == 'confirm', expected_revision=request.POST.get('revision',''))
    except MuseError as error:
        return workspace(request, project, session, error=error.message)
    return back(project, session)


@require_POST
def specification(request, project_id, session_id):
    project = get_object_or_404(Project, pk=project_id)
    session = get_session(project, session_id)
    form = SpecificationForm(request.POST, project=project)
    if form.is_valid():
        try:
            session = save_decisions(session, form, expected_revision=request.POST.get('revision',''))
        except MuseError as error:
            return workspace(request, project, session, error=error.message, specification_form=form)
        return back(project, session)
    return workspace(request, project, session, specification_form=form)


@require_POST
def generate(request, project_id, session_id):
    from .generation import queue_generation
    project = get_object_or_404(Project, pk=project_id)
    session = get_session(project, session_id)
    try:
        operation = queue_generation(session, expected_revision=request.POST.get('revision',''))
    except MuseError as error:
        session.refresh_from_db()
        return workspace(request, project, session, error=error.message)
    launch(operation)
    return back(project, session)


@require_POST
def confirm(request, project_id, session_id):
    project = get_object_or_404(Project, pk=project_id)
    session = get_session(project, session_id)
    try:
        session = confirm_specification(session, expected_revision=request.POST.get('revision',''))
    except MuseError as error:
        return workspace(request, project, session, error=error.message)
    return back(project, session)
