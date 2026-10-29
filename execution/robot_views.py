from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from projects.models import DatasetRow
from .limits import MAX_TEST_ROWS
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
        'attempts':attempts, 'queue':queue,'active_execution':RobotRun.objects.filter(active_slot='local').first(),
        'has_runnable_version':robot.builds.filter(is_draft=True,status='validated',specification_snapshot__isnull=False).exists(),
        'max_test_rows':MAX_TEST_ROWS})


@require_http_methods(['GET','POST'])
def run_robot(request,robot_id):
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError
    from django.http import Http404, HttpResponse
    from django.shortcuts import redirect
    from django.urls import reverse
    from .forms import RobotRunForm
    from .draft_tests import queue_test,launch_test,reviewed_source,input_schema_matches
    robot=get_object_or_404(Robot.objects.select_related('project'),pk=robot_id)
    versions=robot.builds.filter(is_draft=True,status='validated',specification_snapshot__isnull=False).select_related('robot','specification_snapshot')
    data=request.POST if request.method=='POST' else request.GET
    refresh=request.method=='POST' and data.get('action')=='refresh'
    selected=versions.first()
    if data.get('build'):
        try:
            selected=get_object_or_404(versions,pk=data['build'])
        except (ValueError,ValidationError):
            raise Http404 from None
    form=RobotRunForm(request.POST if request.method=='POST' and not refresh else None,robot=robot,selected_build=selected)
    block=''
    source=''
    if selected:
        source=next(iter(selected.source_files.values()),'')
        try:
            reviewed_source(selected,selected.source_digest)
        except (ValueError,KeyError):
            block='This version needs a current specification and valid source. Review the project and generate a current draft.'
    else:
        block='Generate a validated draft version before running this robot.'
    active=RobotRun.objects.filter(active_slot='local').first()
    if active:
        block='Another execution is active. Wait for it to finish or open its progress page to stop it.'
    elif not form.fields['dataset'].queryset.exists() and not block:
        block='No confirmed dataset has valid pending inputs. Add inputs and confirm their dataset first.'
    if request.method=='POST' and not refresh and form.is_valid() and not block:
        try:
            run=queue_test(form.cleaned_data['build'],form.cleaned_data['dataset'],
                reviewed_digest=form.cleaned_data['reviewed_digest'],acknowledged=form.cleaned_data['acknowledged'],
                row_limit=form.cleaned_data['row_limit'],record_screen=form.cleaned_data['record_screen'])
        except (ValueError,KeyError,IntegrityError):
            form.add_error(None,'The run could not start. Check the selected source, pending inputs and active executions, then review again.')
        else:
            launch_test(run)
            url=reverse('run-detail',args=[run.pk])
            return HttpResponse(headers={'HX-Redirect':url}) if request.headers.get('HX-Request')=='true' else redirect(url)
    if request.method=='GET' or refresh:
        datasets=form.fields['dataset'].queryset
        if data.get('dataset'):
            try:
                dataset=form.fields['dataset'].clean(data['dataset'])
            except ValidationError:
                raise Http404 from None
        else:
            dataset=datasets.first()
        if dataset:
            form.initial['dataset']=dataset.pk
        try:
            limit=int(data.get('row_limit',2))
            form.initial['row_limit']=limit if 1<=limit<=MAX_TEST_ROWS else 2
        except ValueError:
            pass
        form.initial['record_screen']=data.get('record_screen')=='on'
    else:
        dataset=form.fields['dataset'].queryset.filter(pk=form.cleaned_data['dataset'].pk).first() if 'dataset' in form.cleaned_data else None
    if selected and dataset and not block:
        if not input_schema_matches(selected,dataset):
            block='This dataset does not match the selected version’s input definitions. Create a current dataset or choose another one.'
    template='execution/_run_dialog.html' if request.headers.get('HX-Request')=='true' else 'execution/run_robot.html'
    return render(request,template,{'robot':robot,'form':form,'selected_build':selected,'source':source,
        'run_block':block,'active_execution':active,'pending_count':dataset.pending_count if dataset else 0})


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
