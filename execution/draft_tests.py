"""Explicitly reviewed local test execution. This is not a Python sandbox."""
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from muse_builder.client import MuseError
from muse_builder.context import canonical, require_current
from muse_builder.validation import validate_source
from robot_framework.adapters.browser import PlaywrightBrowser
from robot_framework.adapters.email import FakeEmailAdapter
from robot_framework.adapters.secrets import EnvironmentSecrets
from robot_framework.contracts import RunOptions, RunResult, RunState
from robot_framework.registry import Registry, robot_name
from robot_framework.runner import Runner
from .adapters import create_run, DjangoQueue, LeaseCancellation
from .models import RobotRun


def reviewed_source(build, digest):
    if not build.is_draft or build.status != 'validated' or not build.specification_snapshot_id:
        raise ValueError('Choose a statically validated draft version.')
    spec = build.confirmed_specification
    name = robot_name(spec['project_context']['project']['name'])
    sources = build.source_files
    if set(sources) != {name + '.py'} or not isinstance(sources[name + '.py'],str):
        raise ValueError('The saved draft source does not match the expected robot file.')
    source = sources[name + '.py']
    if not digest or sha256(source.encode()).hexdigest() != digest or digest != build.source_digest:
        raise ValueError('Source changed or review fingerprint is missing. Review this version again.')
    if sha256(canonical(spec).encode()).hexdigest() != build.confirmed_specification_hash:
        raise ValueError('The saved specification fingerprint is invalid.')
    if (spec['project_context'] != build.specification_snapshot.project_data
            or build.framework_contract_hash != build.specification_snapshot.contract_hash):
        raise ValueError('The build does not match its saved context.')
    try:
        require_current(build.specification_snapshot)
    except MuseError:
        raise ValueError('The project or framework changed. Review and generate a current draft before testing.') from None
    if validate_source(source, robot_name=name, specification=spec):
        raise ValueError('The draft no longer passes static compatibility checks.')
    return name, source


def queue_test(build, dataset, *, reviewed_digest, acknowledged, row_limit=2, record_screen=False):
    if not acknowledged:
        raise ValueError('Review the source and confirm local execution before testing.')
    if isinstance(row_limit,bool) or not isinstance(row_limit,int) or not 1 <= row_limit <= 5:
        raise ValueError('Choose between 1 and 5 pending rows.')
    if dataset.project_id != build.robot.project_id:
        raise ValueError('Choose a dataset from this robot project.')
    name, _ = reviewed_source(build, reviewed_digest)
    required = {item['key'] for item in build.confirmed_specification['project_context']['input_definitions']}
    supplied = {item['key'] for item in dataset.schema_snapshot}
    if not required <= supplied:
        raise ValueError('This dataset is missing inputs required by the saved specification.')
    with transaction.atomic():
        run = create_run(dataset,name,build=build)
        run.is_test, run.reviewed_source_digest, run.source_reviewed_at = True, reviewed_digest, timezone.now()
        run.test_options = {'row_limit':row_limit,'record_screen':bool(record_screen),'fake_email':True}
        run.save(update_fields=['is_test','reviewed_source_digest','source_reviewed_at','test_options'])
    return run


def launch_test(run):
    try:
        subprocess.Popen([sys.executable,str(settings.BASE_DIR / 'manage.py'),'execute_robot_test',str(run.pk)],
            cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    except OSError:
        DjangoQueue(run).emit('run_failed',summary=RunResult(state=RunState.FAILED,message='Could not start the local test worker.'))


def execute_test(run_id, *, browser_factory=PlaywrightBrowser):
    # A duplicate worker must never import source or replay UI actions.
    if RobotRun.objects.filter(pk=run_id,is_test=True,state='queued',active_slot='local',
            source_reviewed_at__isnull=False).update(state='starting',heartbeat=timezone.now()) != 1:
        return
    run = RobotRun.objects.select_related('build__specification_snapshot','build__robot','dataset').get(pk=run_id)
    queue = DjangoQueue(run)
    try:
        if run.cancel_requested:
            queue.emit('run_cancelled',summary=RunResult(state=RunState.CANCELLED,message='Test cancelled before execution.'))
            return
        name, source = reviewed_source(run.build,run.reviewed_source_digest)
        spec = run.build.confirmed_specification
        context = spec['project_context']
        # Deliberately execute only after explicit source review and worker checks.
        # Ordinary local Python permissions apply; static checks are not isolation.
        namespace = {'__name__':f'reviewed_robot_build_{run.build_id}'}
        exec(compile(source,f'<reviewed robot build {run.build_id}>','exec'),namespace)
        registry = Registry()
        registry.register(name,namespace[name])
        browser = browser_factory({item['id']:item['locator'] for item in context['captured_elements']},
            {str(item['id']):item['target_url'] for item in context['applications']},
            Path(settings.MEDIA_ROOT) / 'runs' / str(run.pk))
        decisions = spec['decisions']
        options = RunOptions(record_screen=run.test_options['record_screen'],stop_on_nok=decisions['stop_on_nok'],
            stop_on_error=decisions['stop_on_error'])
        with LeaseCancellation(run.pk) as cancellation:
            return Runner(registry,browser,EnvironmentSecrets(),queue,cancellation,email=FakeEmailAdapter()).run(
                name,queue.rows(),options,input_fields=[item['key'] for item in run.dataset.schema_snapshot])
    except Exception:
        # Persist fixed diagnostics; never expose exception/source/secret values.
        if RobotRun.objects.filter(pk=run.pk,active_slot='local').exists():
            queue.emit('run_failed',summary=RunResult(state=RunState.FAILED,
                message='Local draft test could not complete. Review the saved source, target application and test configuration.'))
