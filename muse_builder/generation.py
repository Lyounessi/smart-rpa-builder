"""Budgeted draft generation. Generated source is data, never imported or executed."""
from copy import deepcopy
from hashlib import sha256
import logging

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Max
from django.utils import timezone
from pydantic import ValidationError

from execution.models import Robot, RobotBuild
from robot_framework.registry import robot_name
from .client import MetaConfiguration, MuseError
from .budget import SpendingPolicy
from .context import canonical, require_current
from .conversation import check_idle, check_revision, guard_text, local_issues, reset_confirmation, revision
from .generation_schema import GenerationResponse
from .models import BuildMessage, BuildOperation, BuildQuestion, BuildSession, GenerationJob, MuseBudget, MuseRequest
from .validation import validate_source

logger = logging.getLogger(__name__)


def require_confirmed(session, job=None):
    require_current(session.snapshot)
    spec = session.confirmed_specification
    digest = sha256(canonical(spec).encode()).hexdigest()
    if (not session.confirmed_at or not spec or digest != session.confirmed_hash
            or spec.get('source_specification_hash') != session.snapshot.specification_hash
            or spec.get('project_context') != session.snapshot.project_data
            or spec.get('framework_contract_version') != session.snapshot.contract_version
            or spec.get('framework_contract_hash') != session.snapshot.contract_hash
            or spec.get('decisions') != session.decisions or spec.get('assumptions') != session.assumptions
            or session.questions.filter(resolved=False).exists() or session.proposals.filter(status='pending').exists()
            or local_issues(session)):
        raise MuseError('unconfirmed_specification', 'Confirm a complete, current specification before generating a robot.')
    if job and (job.confirmed_hash != digest or job.snapshot_id != session.snapshot_id
                or job.confirmed_specification != spec):
        raise MuseError('stale_specification', 'The confirmed specification changed. This generation was discarded.')


def new_operation(job, kind):
    return BuildOperation.objects.create(session=job.session, generation=job, kind=kind,
        heartbeat=timezone.now(), expected_revision=revision(job.session),
        round_number=(job.session.operations.aggregate(value=Max('round_number'))['value'] or 0) + 1)


def queue_generation(session, *, expected_revision=None):
    from django.conf import settings
    config = MetaConfiguration.from_settings()
    policy = SpendingPolicy.load(config.model)
    try:
        cap = int(settings.MUSE_GENERATION_OUTPUT_TOKENS)
        if not 1024 <= cap <= min(16384, policy.output_cap):
            raise ValueError()
    except (TypeError, ValueError):
        raise MuseError('request_limit', 'Generation output tokens must be 1024–16384 and within the configured output cap.') from None
    budget = MuseBudget.objects.filter(pk=1).first()
    if (budget.committed_usd if budget else 0) + policy.reservation(cap) > policy.limit:
        raise MuseError('budget_exhausted', 'The local spending limit cannot cover another generation request.')
    try:
        with transaction.atomic():
            session = BuildSession.objects.select_for_update().select_related('snapshot','project').get(pk=session.pk)
            check_idle(session)
            check_revision(session, expected_revision)
            require_confirmed(session)
            if MuseRequest.objects.filter(active_slot='local').exists():
                raise MuseError('operation_active', 'Another Muse request is active. Wait before generating.')
            try:
                name = robot_name(session.project.name)
            except ValueError:
                raise MuseError('invalid_name', 'The project name needs letters or numbers for its robot name.') from None
            job = GenerationJob.objects.create(session=session, snapshot=session.snapshot, robot_name=name,
                confirmed_specification=deepcopy(session.confirmed_specification), confirmed_hash=session.confirmed_hash)
            session.state, session.error_message = 'generating', ''
            session.save(update_fields=['state','error_message'])
            job.session = session
            return new_operation(job, 'generation')
    except (IntegrityError, OperationalError):
        raise MuseError('operation_active', 'Another build operation is queued or active. No generation was started.') from None


def close_operation(operation, *, status='success', message=''):
    operation.status, operation.active_slot, operation.finished_at = status, None, timezone.now()
    operation.error_message = message[:400]
    operation.save()


def fail_generation(job_id, message, *, stale=False):
    with transaction.atomic():
        job = GenerationJob.objects.select_for_update().get(pk=job_id)
        if job.state in {'generated','needs_clarification','failed'}:
            return
        job.state, job.error_message, job.finished_at = 'failed', message[:400], timezone.now()
        job.save()
        job.operations.filter(active_slot='local').update(status='failed', active_slot=None,
            finished_at=timezone.now(), error_message=message[:400])
        session = BuildSession.objects.get(pk=job.session_id)
        session.state, session.error_message = 'failed', message[:400]
        if stale:
            reset_confirmation(session)
        session.save()


def return_questions(job, operation, response):
    session = job.session
    message = BuildMessage.objects.create(session=session, role='assistant', review_status='confirmed',
        content='Generation needs clarification before a draft can be saved.',
        structured={'questions':[], 'assumptions':response.assumptions})
    questions = []
    for index, text in enumerate(response.clarification_questions):
        key = f'gen_{str(job.pk)[:8]}_{index + 1}'
        BuildQuestion.objects.create(session=session, message=message, key=key, text=text)
        questions.append({'id':key,'text':text,'choices':[]})
    message.structured['questions'] = questions
    message.save(update_fields=['structured'])
    session.state, session.model_ready, session.manual_reviewed = 'needs_clarification', False, False
    reset_confirmation(session)
    session.save()
    job.state, job.finished_at = 'needs_clarification', timezone.now()
    job.save()
    close_operation(operation)


def save_draft(job, operation, response):
    session = job.session
    robot, _ = Robot.objects.get_or_create(project=session.project, defaults={'name':job.robot_name})
    robot = Robot.objects.select_for_update().get(pk=robot.pk)
    version = (robot.builds.aggregate(value=Max('version'))['value'] or 0) + 1
    build = RobotBuild.objects.create(robot=robot, version=version, origin='muse', status='validated', is_draft=True,
        source_files={job.robot_name + '.py':response.source_code},
        source_digest=sha256(response.source_code.encode()).hexdigest(),
        configuration={'robot_name':job.robot_name,'class_name':job.robot_name,'execution_enabled':False,
                       'decisions':deepcopy(job.confirmed_specification['decisions'])},
        specification_snapshot=job.snapshot, confirmed_specification=deepcopy(job.confirmed_specification),
        confirmed_specification_hash=job.confirmed_hash,
        framework_contract_version=job.snapshot.contract_version, framework_contract_hash=job.snapshot.contract_hash,
        assumptions=response.assumptions,
        validation_report=['Static compatibility checks passed. Source was never imported or executed.',
            'Draft only. Static checks do not prove safety, business correctness or successful execution. Review and explicit testing are required.'])
    job.result_build, job.state, job.finished_at = build, 'generated', timezone.now()
    job.save()
    session.state = 'generated'
    session.save(update_fields=['state'])
    close_operation(operation)


def run_generation(job_id, *, service=None):
    from .service import MuseService
    # A worker can claim only the initial queued operation. Repairs belong to that worker.
    with transaction.atomic():
        operation = BuildOperation.objects.filter(generation_id=job_id, kind='generation', status='queued', active_slot='local').first()
        if operation is None or BuildOperation.objects.filter(pk=operation.pk, status='queued').update(status='running') != 1:
            return
        GenerationJob.objects.filter(pk=job_id).update(state='running')
    previous, errors = None, None
    stage = 'context_check'
    try:
        for attempt in range(3):
            stage = 'context_check'
            job = GenerationJob.objects.select_related('session__snapshot','session__project','snapshot').get(pk=job_id)
            require_confirmed(job.session, job)
            stage = 'provider_request'
            result = (service or MuseService()).generate_draft(job, build_operation=operation, previous=previous, errors=errors)
            stage = 'response_check'
            guard_text(result.text)
            try:
                response = GenerationResponse.model_validate_json(result.text)
                payload = response.model_dump()
            except ValidationError:
                response = None
                payload = {'invalid_response':result.text[:65536]}
            # Keep the paid response even if validation or saving subsequently fails.
            # Never persist responses containing known configured credentials.
            require_confirmed(job.session, job)
            stage = 'response_save'
            if BuildOperation.objects.filter(pk=operation.pk, active_slot='local', status='running').update(response_payload=payload) != 1:
                raise MuseError('operation_closed', 'Generation operation was closed. Response discarded.')
            stage = 'static_validation'
            errors = ([] if response.clarification_questions else validate_source(response.source_code,
                robot_name=job.robot_name, specification=job.confirmed_specification)) if response else [
                    'Return the exact structured response with bounded source_code, assumptions and clarification_questions.']
            stage = 'draft_save'
            with transaction.atomic():
                # SQLite has no SELECT FOR UPDATE. Acquire write ownership before
                # reading so the heartbeat cannot cause a read-to-write lock upgrade.
                if BuildOperation.objects.filter(pk=operation.pk, active_slot='local', status='running').update(heartbeat=timezone.now()) != 1:
                    raise MuseError('operation_closed', 'Generation operation was closed. Response discarded.')
                job.session = BuildSession.objects.select_for_update().select_related('project','snapshot').get(pk=job.session_id)
                require_confirmed(job.session, job)
                operation.refresh_from_db()
                if operation.active_slot != 'local' or operation.status != 'running':
                    raise MuseError('operation_closed', 'Generation operation was closed. Response discarded.')
                operation.response_payload, operation.validation_errors = payload, errors
                operation.save(update_fields=['response_payload','validation_errors'])
                if response and response.clarification_questions:
                    return_questions(job, operation, response)
                    return
                if not errors:
                    save_draft(job, operation, response)
                    return
                MuseRequest.objects.filter(build_operation=operation).update(outcome='failed', error_code='static_validation')
                close_operation(operation, status='failed', message='Draft failed static compatibility checks.')
                if attempt < 2:
                    previous = payload
                    operation = new_operation(job, 'repair')
                    operation.status = 'running'
                    operation.save(update_fields=['status'])
                else:
                    fail_generation(job_id, 'Draft failed static checks after the initial request and two repair attempts. Review the saved diagnostics before starting a new generation.')
                    return
    except MuseError as error:
        MuseRequest.objects.filter(build_operation=operation, outcome='success').update(
            outcome='stale' if error.code == 'stale_specification' else 'failed', error_code=error.code)
        fail_generation(job_id, error.message, stale=error.code in {'stale_specification','unconfirmed_specification'})
    except Exception as error:
        # Log identifiers/types only: exception messages and trace locals may contain
        # source, inputs, provider payloads or secrets.
        category = type(error).__name__
        logger.error('Muse generation %s failed at %s (%s)', job_id, stage, category)
        request = MuseRequest.objects.filter(build_operation=operation).first()
        MuseRequest.objects.filter(build_operation=operation, outcome='success').update(outcome='failed', error_code='local_processing')
        accounting = ('Recorded API usage is retained; no additional request was sent.' if request and request.usage_known
            else 'Any uncertain API reservation is retained; no automatic retry was made.')
        message = f'Local generation processing failed at {stage} ({category}). {accounting} No draft was activated.'
        BuildOperation.objects.filter(pk=operation.pk).update(validation_errors=[f'Local processing failure: {stage} ({category}).'])
        fail_generation(job_id, message)
