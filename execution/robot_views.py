from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from projects.models import DatasetRow
from .models import Robot, RobotBuild, RobotRun, RowAttempt


def seconds(start, finish):
    return max(0, (finish - start).total_seconds()) if start and finish else None


def duration(value):
    if value is None:
        return 'Not recorded'
    if value >= 3600:
        return f'{int(value // 3600)}h {int(value % 3600 // 60)}m {value % 60:.1f}s'
    if value >= 60:
        return f'{int(value // 60)}m {value % 60:.1f}s'
    return f'{value:.1f}s'


def run_metrics(run):
    if run is None:
        return None
    attempts = list(run.attempts.all())
    completed = sum(item.business_completed_at is not None or item.outcome == 'OK' for item in attempts)
    measured = [seconds(item.started_at, item.finished_at) for item in attempts]
    measured = [value for value in measured if value is not None]
    end = run.finished_at or (timezone.now() if run.active_slot and run.state == 'running' else None)
    return {'attempted':len(attempts), 'business_completed':completed,
        'ok':sum(item.outcome == 'OK' for item in attempts),
        'nok':sum(item.outcome == 'NOK' for item in attempts),
        'errors':sum(item.outcome == 'ERROR' for item in attempts),
        'unconfirmed':sum(not item.outcome for item in attempts),
        'elapsed':duration(seconds(run.started_at, end)),
        'average':duration(sum(measured) / len(measured) if measured else None),
        'timed_rows':len(measured), 'completion_rate':f'{100 * completed / len(attempts):.1f}%' if attempts else '—'}


@require_GET
def robot_list(request):
    latest_build = RobotBuild.objects.filter(robot_id=OuterRef('pk')).order_by('-version')
    latest_run = RobotRun.objects.filter(dataset__project_id=OuterRef('project_id')).order_by('-created_at')
    pending = DatasetRow.objects.filter(dataset__project_id=OuterRef('project_id'), dataset__status='ready',
        errors=[], processing_status='pending',deleted_at__isnull=True).values('dataset__project_id').annotate(total=Count('pk')).values('total')
    completed = RowAttempt.objects.filter(run__dataset__project_id=OuterRef('project_id')).filter(
        Q(business_completed_at__isnull=False) | Q(outcome='OK')).values('run__dataset__project_id').annotate(total=Count('row_id', distinct=True)).values('total')
    robots = Robot.objects.select_related('project').annotate(
        latest_version=Subquery(latest_build.values('version')[:1]),
        build_status=Subquery(latest_build.values('status')[:1]),
        build_is_draft=Subquery(latest_build.values('is_draft')[:1]),
        build_origin=Subquery(latest_build.values('origin')[:1]),
        last_state=Subquery(latest_run.values('state')[:1]), last_run_id=Subquery(latest_run.values('pk')[:1]),
        last_run_at=Subquery(latest_run.values('created_at')[:1]),
        pending_count=Coalesce(Subquery(pending), Value(0)), completed_count=Coalesce(Subquery(completed), Value(0))).order_by('-updated_at', '-pk')
    return render(request, 'execution/robots.html', {'page':Paginator(robots, 20).get_page(request.GET.get('page'))})


@require_GET
def robot_detail(request, robot_id):
    robot = get_object_or_404(Robot.objects.select_related('project'), pk=robot_id)
    runs = RobotRun.objects.filter(dataset__project=robot.project).select_related('dataset', 'build').annotate(
        attempted_count=Count('attempts'),
        business_count=Count('attempts', filter=Q(attempts__business_completed_at__isnull=False) | Q(attempts__outcome='OK')),
        nok_count=Count('attempts', filter=Q(attempts__outcome='NOK')),
        error_count=Count('attempts', filter=Q(attempts__outcome='ERROR'))).order_by('-created_at')
    selected = request.GET.get('run')
    if selected:
        from django.core.exceptions import ValidationError
        from django.http import Http404
        try:
            run = get_object_or_404(runs, pk=selected)
        except (ValidationError, ValueError):
            raise Http404('Unknown run.') from None
    else:
        run = runs.first()
    history = Paginator(runs, 15).get_page(request.GET.get('history_page'))
    for entry in history:
        entry.elapsed = duration(seconds(entry.started_at, entry.finished_at or (timezone.now() if entry.active_slot and entry.state == 'running' else None)))
    attempts = None
    if run:
        attempts = Paginator(run.attempts.select_related('row').prefetch_related('actions').annotate(
            total_attempts=Count('row__rowattempt')).order_by('row__row_number'), 25).get_page(request.GET.get('rows_page'))
        for attempt in attempts:
            attempt.cells = [attempt.input_snapshot.get(key, '') if attempt.input_snapshot is not None else 'Not recorded'
                             for key in run.dataset.headers]
            attempt.elapsed = duration(seconds(attempt.started_at, attempt.finished_at))
    queue = DatasetRow.objects.filter(dataset__project=robot.project, dataset__status='ready', errors=[],deleted_at__isnull=True).aggregate(
        pending=Count('pk', filter=Q(processing_status='pending')), in_progress=Count('pk', filter=Q(processing_status='in_progress')),
        done=Count('pk', filter=Q(processing_status='done')))
    return render(request, 'execution/robot_detail.html', {'robot':robot, 'builds':Paginator(robot.builds.all(), 10).get_page(request.GET.get('builds_page')),
        'latest_build':robot.builds.first(), 'history':history, 'selected_run':run, 'metrics':run_metrics(run),
        'attempts':attempts, 'queue':queue})


@require_GET
def build_detail(request, robot_id, version):
    from .forms import DraftTestForm
    build = get_object_or_404(RobotBuild.objects.select_related('robot__project'), robot_id=robot_id, version=version)
    return render(request, 'execution/build_detail.html', {'build':build,
        'test_runs':build.runs.filter(is_test=True).order_by('-created_at')[:10],
        'test_form':DraftTestForm(build=build) if build.is_draft else None})


@require_POST
def test_build(request, robot_id, version):
    from django.db import IntegrityError
    from django.shortcuts import redirect
    from .forms import DraftTestForm
    from .draft_tests import queue_test, launch_test
    build = get_object_or_404(RobotBuild.objects.select_related('robot__project','specification_snapshot'),robot_id=robot_id,version=version)
    form = DraftTestForm(request.POST,build=build)
    if form.is_valid():
        try:
            run = queue_test(build,form.cleaned_data['dataset'],
                reviewed_digest=form.cleaned_data['reviewed_digest'],acknowledged=form.cleaned_data['acknowledged'],
                row_limit=form.cleaned_data['row_limit'],record_screen=form.cleaned_data['record_screen'])
        except (ValueError,KeyError,IntegrityError):
            form.add_error(None,'Cannot start this test. Check that the source and project are current, the dataset has valid pending rows, and no other robot run is active.')
        else:
            launch_test(run)
            return redirect('run-detail',run_id=run.pk)
    return render(request,'execution/build_detail.html',{'build':build,'test_form':form,
        'test_runs':build.runs.filter(is_test=True).order_by('-created_at')[:10]})
