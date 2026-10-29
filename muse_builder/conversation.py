"""Bounded, explicitly confirmed specification building. No robot generation."""
from copy import deepcopy
import hashlib
import json
import os
import subprocess
import sys

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Max
from django.utils import timezone
from pydantic import ValidationError as SchemaError

from projects.forms import AutomationBriefForm, StepForm
from projects.models import Project
from .budget import SpendingPolicy
from .client import MetaConfiguration, MuseError
from .context import canonical, create_snapshot, require_current
from .conversation_schema import ClarificationResponse
from .forms import SpecificationForm, decision_form_data
from .models import BuildMessage, BuildOperation, BuildProposal, BuildQuestion, BuildSession, MuseRequest

MAX_ROUNDS = 3
DECISION_FIELDS = {'setup_step_ids','per_row_step_ids','stop_on_nok','stop_on_error','success_criteria','rejection_handling','recovery_plan'}
BRIEF_FIELDS = {'automation_goal':'automation_goal','global_rules':'global_rules','brief_success_criteria':'success_criteria'}


def guard_text(text):
    secrets = [settings.MUSE_APIKEY, settings.SECRET_KEY]
    secrets += [value for key,value in os.environ.items() if key.startswith('RPA_SECRET_')]
    if any(value and len(value) >= 8 and value in text for value in secrets):
        raise MuseError('sensitive_context', 'Known credentials were detected. Remove secrets before continuing.')


def revision(session):
    data = {'snapshot':session.snapshot.specification_hash,'decisions':session.decisions,'assumptions':session.assumptions,
            'questions':list(session.questions.order_by('pk').values('key','answer','resolved')),
            'proposals':list(session.proposals.order_by('pk').values('id','status')),
            'rounds_used':session.rounds_used,'latest_message':session.messages.order_by('-pk').values_list('pk',flat=True).first(),
            'state':session.state,'confirmed_hash':session.confirmed_hash}
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def check_idle(session):
    if session.operations.filter(active_slot='local').exists():
        raise MuseError('operation_active', 'Wait for the current review to finish.')
    require_current(session.snapshot)


def check_revision(session, expected):
    if expected is not None and revision(session) != expected:
        raise MuseError('stale_session', 'This form is out of date. Reload the review before confirming or sending changes.')


def reset_confirmation(session):
    session.confirmed_at = None
    session.confirmed_specification = {}
    session.confirmed_hash = ''


def local_issues(session):
    form = SpecificationForm(decision_form_data(session.decisions), project=session.project)
    issues = []
    if not form.is_valid():
        issues.extend(f'{field}: {" ".join(errors)}' for field,errors in form.errors.items())
    for step in session.snapshot.project_data['steps']:
        if step['action'] not in {'click','fill','select'}:
            issues.append(f'Step {step["id"]} needs a supported action in the project editor.')
        if not step['application_id'] or not step['element_ids']:
            issues.append(f'Step {step["id"]} needs its target application and captured element.')
    return issues


def refresh_state(session):
    latest = session.messages.filter(role='assistant').last()
    unsupported = latest.structured.get('unsupported_requests', []) if latest else []
    ready = (session.model_ready or session.manual_reviewed) and not local_issues(session) and not unsupported
    ready = ready and not session.questions.filter(resolved=False).exists() and not session.proposals.filter(status='pending').exists()
    session.state = 'ready_to_generate' if ready else 'needs_clarification'
    session.error_message = ''


def initial_decisions(project):
    return {'setup_step_ids':[], 'per_row_step_ids':[], 'stop_on_nok':False, 'stop_on_error':True,
            'success_criteria':project.success_criteria, 'rejection_handling':'', 'recovery_plan':''}


def queue_review(session, *, content, answers=None, include_images=False, expected_revision=None):
    MetaConfiguration.from_settings()
    SpendingPolicy.load(settings.META_MODEL)
    guard_text(content)
    try:
        with transaction.atomic():
            session = BuildSession.objects.select_for_update().select_related('project','snapshot').get(pk=session.pk)
            check_idle(session)
            check_revision(session, expected_revision)
            if MuseRequest.objects.filter(active_slot='local').exists():
                raise MuseError('operation_active', 'Another Muse API operation is active. Wait for it to finish.')
            if session.rounds_used >= MAX_ROUNDS:
                raise MuseError('round_limit', 'Three review rounds have been used. Edit the specification locally instead.')
            if session.proposals.filter(status='pending').exists():
                raise MuseError('pending_proposals', 'Confirm or reject the proposed changes before another paid review.')
            for pk, answer in (answers or {}).items():
                guard_text(answer)
                session.questions.filter(pk=pk, resolved=False).update(answer=answer)
            BuildMessage.objects.create(session=session, role='user', content=content)
            session.rounds_used += 1
            session.model_ready = session.manual_reviewed = False
            reset_confirmation(session)
            session.state, session.error_message = 'needs_clarification', ''
            session.save()
            operation = BuildOperation.objects.create(session=session, heartbeat=timezone.now(), round_number=(session.operations.aggregate(value=Max('round_number'))['value'] or 0) + 1,
                expected_revision=revision(session), include_images=include_images)
    except (IntegrityError, OperationalError):
        raise MuseError('operation_active', 'Another Muse review is queued or active. No new review was started.') from None
    return operation


def launch(operation):
    try:
        command, identifier = ('review_muse_session', operation.pk) if operation.kind == 'clarification' else ('generate_muse_robot', operation.generation_id)
        subprocess.Popen([sys.executable, str(settings.BASE_DIR / 'manage.py'), command, str(identifier)],
            cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    except OSError:
        if operation.kind == 'clarification':
            fail_operation(operation.pk, 'Could not start the local review worker. Check the Python environment.')
        else:
            from .generation import fail_generation
            fail_generation(operation.generation_id, 'Could not start the local generation worker. Check the Python environment.')


def start_session(project):
    MetaConfiguration.from_settings()
    if not project.steps.exists():
        raise MuseError('empty_workflow', 'Add workflow steps before starting a Muse review.')
    if BuildOperation.objects.filter(active_slot='local').exists():
        raise MuseError('operation_active', 'Another Muse review is queued or active. Wait for it to finish.')
    snapshot = create_snapshot(project)
    with transaction.atomic():
        session = BuildSession.objects.create(project=project, snapshot=snapshot, decisions=initial_decisions(project))
        operation = queue_review(session, content='Review my saved workflow. Ask only the questions needed to make its specification clear.', include_images=True)
    launch(operation)
    return session


def conversation_state(session):
    recent = list(session.messages.order_by('-pk').values('role','content')[:4])
    return {'decisions':session.decisions, 'confirmed_assumptions':session.assumptions,
            'policy_source':'framework defaults until explicitly confirmed',
            'outstanding_questions':list(session.questions.filter(resolved=False).values('key','text','choices','answer')),
            'remaining_rounds':MAX_ROUNDS - session.rounds_used,
            'local_missing_requirements':local_issues(session), 'recent_exchanges':list(reversed(recent))}


def proposal_plan(session, proposals):
    decisions, plans, changed = deepcopy(session.decisions), [], set()
    for proposal in proposals:
        key = (proposal.field, proposal.step_id)
        if key in changed:
            raise MuseError('invalid_proposal', 'A response proposed contradictory updates to the same field.')
        changed.add(key)
        field, value = proposal.field, proposal.value
        guard_text(value)
        if field in DECISION_FIELDS:
            if proposal.step_id is not None:
                raise MuseError('invalid_proposal', 'Decision changes cannot target a workflow step.')
            form = SpecificationForm(project=session.project)
            if field.endswith('_step_ids'):
                try:
                    ids = json.loads(value)
                    if not isinstance(ids,list) or any(type(pk) is not int for pk in ids) or len(ids) != len(set(ids)):
                        raise ValueError()
                    cleaned = form.fields[field].clean(ids)
                    value = list(cleaned.values_list('pk',flat=True))
                except (ValueError, ValidationError):
                    raise MuseError('invalid_proposal', 'Invalid setup/per-row step allocation.') from None
            else:
                try:
                    value = form.fields[field].clean(value)
                except ValidationError:
                    raise MuseError('invalid_proposal', 'A proposed decision has an unsupported value.') from None
            decisions[field] = value
        elif field in BRIEF_FIELDS:
            if proposal.step_id is not None:
                raise MuseError('invalid_proposal', 'Brief changes cannot target a step.')
            project = Project.objects.get(pk=session.project_id)
            values = {name:getattr(project,name) for name in AutomationBriefForm.Meta.fields}
            values[BRIEF_FIELDS[field]] = value
            form = AutomationBriefForm(values, instance=project)
            if not form.is_valid():
                raise MuseError('invalid_proposal', 'Invalid proposed brief change.')
            plans.append(form)
        else:
            if proposal.step_id is None:
                raise MuseError('invalid_proposal', 'A workflow change requires a step ID.')
            try:
                step = session.project.steps.get(pk=proposal.step_id)
            except Exception:
                raise MuseError('invalid_proposal', 'A proposed step does not belong to this project.') from None
            reference = step.element_references.first()
            values = {'name':step.name,'instruction':step.instruction,'window':step.window_id or '', 'action':step.action,
                      'input_column':step.input_column_id or '', 'target':str(reference.element_id) if reference else ''}
            if field == 'step_instruction':
                values['instruction'] = value
            elif field == 'step_input_mapping':
                if step.action not in {'fill','select'}:
                    raise MuseError('invalid_proposal', 'Only Fill and Select option steps accept input mappings.')
                column = session.project.inputs.filter(key=value).first()
                if column is None:
                    raise MuseError('invalid_proposal', 'The proposed input key is not defined in this project.')
                values['input_column'] = column.pk
            elif field == 'step_target':
                if value not in {element['id'] for element in session.snapshot.project_data['captured_elements']}:
                    raise MuseError('invalid_proposal', 'A proposed target is not in the reviewed context.')
                values['target'] = value
            form = StepForm(values, instance=step, project=session.project)
            if not form.is_valid():
                raise MuseError('invalid_proposal', 'A proposed workflow change violates the existing target or mapping rules.')
            plans.append(form)
    if set(decisions.get('setup_step_ids',[])) & set(decisions.get('per_row_step_ids',[])):
        raise MuseError('invalid_proposal', 'Setup and per-row allocations must not overlap.')
    return decisions, plans


def fail_operation(operation_id, message):
    with transaction.atomic():
        operation = BuildOperation.objects.select_for_update().get(pk=operation_id)
        if operation.active_slot is None:
            return
        operation.status, operation.active_slot, operation.finished_at = 'failed', None, timezone.now()
        operation.error_message = message[:400]
        operation.save()
        BuildSession.objects.filter(pk=operation.session_id).update(state='failed', error_message=message[:400])


def run_review(operation_id, *, service=None):
    from .service import MuseService
    with transaction.atomic():
        claimed = BuildOperation.objects.filter(pk=operation_id, kind='clarification', status='queued', active_slot='local').update(status='running', heartbeat=timezone.now())
        if claimed != 1:
            return
        operation = BuildOperation.objects.select_related('session__snapshot','session__project').get(pk=operation_id)
    session = operation.session
    try:
        if revision(session) != operation.expected_revision:
            raise MuseError('stale_session', 'The session changed before this review started.')
        result = (service or MuseService()).clarify(session.snapshot, conversation_state(session),
            build_operation=operation, include_images=operation.include_images)
        guard_text(result.text)
        try:
            response = ClarificationResponse.model_validate_json(result.text)
        except SchemaError:
            raise MuseError('invalid_structured_response', 'Muse returned an invalid or over-limit clarification response. No automatic retry was made.') from None
        proposal_plan(session, response.proposed_changes)
        known = {q.key:q for q in session.questions.all()}
        if any(key not in known or not known[key].answer or known[key].resolved for key in response.resolved_question_ids):
            raise MuseError('invalid_structured_response', 'Muse tried to resolve a question without a recorded answer.')
        for question in response.questions:
            if question.id in known and (known[question.id].resolved or known[question.id].text != question.text):
                raise MuseError('invalid_structured_response', 'Muse reused a question identifier inconsistently.')
        with transaction.atomic():
            current = BuildSession.objects.select_for_update().select_related('snapshot','project').get(pk=session.pk)
            current_op = BuildOperation.objects.select_for_update().get(pk=operation.pk)
            require_current(current.snapshot)
            if current_op.active_slot is None or revision(current) != operation.expected_revision:
                raise MuseError('stale_session', 'Session changed while Muse was reviewing it. Response was not applied.')
            message = BuildMessage.objects.create(session=current, role='assistant', content=response.summary, raw_response=result.text, structured=response.model_dump())
            for question in response.questions:
                BuildQuestion.objects.get_or_create(session=current, key=question.id,
                    defaults={'message':message,'text':question.text,'choices':question.choices})
            for proposal in response.proposed_changes:
                BuildProposal.objects.create(session=current, message=message, **proposal.model_dump())
            current.model_ready = response.state == 'ready_to_generate'
            refresh_state(current)
            current.save()
            current_op.status, current_op.active_slot, current_op.finished_at = 'success', None, timezone.now()
            current_op.save()
    except MuseError as error:
        MuseRequest.objects.filter(build_operation=operation, outcome='success').update(outcome='failed', error_code=error.code)
        fail_operation(operation.pk, error.message)
    except Exception:
        fail_operation(operation.pk, 'The review worker could not complete. Review usage before retrying; no automatic retry was made.')


@transaction.atomic
def review_proposals(session, message_id, *, accept, expected_revision=None):
    session = BuildSession.objects.select_for_update().select_related('project','snapshot').get(pk=session.pk)
    check_idle(session)
    check_revision(session, expected_revision)
    try:
        message = session.messages.get(pk=message_id, role='assistant', review_status='pending')
    except BuildMessage.DoesNotExist:
        raise MuseError('already_reviewed', 'This update was already reviewed or is unavailable.') from None
    proposals = list(message.proposals.filter(status='pending'))
    if message.proposals.exclude(status='pending').exists():
        raise MuseError('already_reviewed', 'These changes were already reviewed and cannot be reapplied.')
    if accept:
        response = ClarificationResponse.model_validate(message.structured)
        decisions, plans = proposal_plan(session, response.proposed_changes)
        # Rebuild each form against current DB state while applying a batch so
        # separate changes to one model cannot overwrite one another.
        for proposal in response.proposed_changes:
            if proposal.field not in DECISION_FIELDS:
                _, forms = proposal_plan(session, [proposal])
                for form in forms:
                    form.save()
        session.decisions = decisions
        session.assumptions = list(dict.fromkeys(session.assumptions + response.assumptions))
        session.questions.filter(key__in=response.resolved_question_ids).exclude(answer='').update(resolved=True)
        if plans:
            session.snapshot = create_snapshot(Project.objects.get(pk=session.project_id))
        message.review_status = 'confirmed'
        for proposal in proposals:
            proposal.status = 'confirmed'
            proposal.save(update_fields=['status'])
    else:
        message.review_status = 'rejected'
        session.model_ready = False
        message.proposals.filter(status='pending').update(status='rejected')
    message.reviewed_at = timezone.now()
    message.save(update_fields=['review_status','reviewed_at'])
    reset_confirmation(session)
    session.manual_reviewed = False
    refresh_state(session)
    session.save()
    return session


@transaction.atomic
def save_decisions(session, form, *, expected_revision=None):
    session = BuildSession.objects.select_for_update().select_related('project','snapshot').get(pk=session.pk)
    check_idle(session)
    check_revision(session, expected_revision)
    latest = session.messages.filter(role='assistant').last()
    if latest and latest.structured.get('unsupported_requests'):
        raise MuseError('unsupported', 'Correct unsupported requests in the project and start a fresh review.')
    if session.questions.filter(resolved=False).exists() and not form.cleaned_data['resolve_questions']:
        raise MuseError('unresolved_questions', 'Explicitly confirm that the listed questions are resolved by these decisions.')
    session.decisions = form.decisions()
    guard_text(canonical(session.decisions))
    session.questions.filter(resolved=False).update(resolved=True)
    message_ids = list(session.proposals.filter(status='pending').values_list('message_id',flat=True))
    session.proposals.filter(status='pending').update(status='rejected')
    session.messages.filter(pk__in=message_ids, review_status='pending').update(review_status='rejected', reviewed_at=timezone.now())
    session.manual_reviewed = True
    reset_confirmation(session)
    refresh_state(session)
    session.save()
    BuildMessage.objects.create(session=session, role='user', content='I explicitly saved the structured specification decisions and resolved the listed questions.',
        structured={'confirmed_decisions':session.decisions, 'resolved_question_ids':list(session.questions.filter(resolved=True).values_list('key',flat=True))}, review_status='confirmed')
    return session


@transaction.atomic
def confirm_specification(session, *, expected_revision=None):
    session = BuildSession.objects.select_for_update().select_related('snapshot','project').get(pk=session.pk)
    check_idle(session)
    check_revision(session, expected_revision)
    refresh_state(session)
    if session.state != 'ready_to_generate':
        raise MuseError('not_ready', 'Resolve questions, confirm changes, and complete the specification first.')
    if session.confirmed_at is not None:
        return session
    session.confirmed_specification = {'project_context':session.snapshot.project_data,'decisions':session.decisions,
        'assumptions':session.assumptions,'source_specification_hash':session.snapshot.specification_hash,
        'clarifications':list(session.questions.filter(resolved=True).order_by('pk').values('key','text','answer')),
        'framework_contract_version':session.snapshot.contract_version,'framework_contract_hash':session.snapshot.contract_hash}
    session.confirmed_hash = hashlib.sha256(canonical(session.confirmed_specification).encode()).hexdigest()
    session.confirmed_at = timezone.now()
    session.save()
    return session
