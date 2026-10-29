from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from .models import RobotRun


def progress_context(run):
    from .robot_views import duration,seconds
    attempts=list(run.attempts.select_related('row').prefetch_related('actions').order_by('pk'))
    counts={key:sum(item.outcome==key for item in attempts) for key in ['OK','NOK','ERROR']}
    finished=sum(counts.values())
    planned=run.test_options.get('planned_rows') if run.is_test else None
    event=run.events.filter(kind__in=['step_started','step_completed','step_failed','row_started','row_finished']).order_by('-pk').first()
    current_step=event.step if event and event.kind=='step_started' else ('Preparing input' if event and event.kind=='row_started' else 'Between steps')
    state='Stopping…' if run.active_slot and run.cancel_requested else {
        'queued':'Queued','starting':'Starting','running':'Running','cancelled':'Stopped',
        'completed':'Completed with issues' if counts['NOK'] or counts['ERROR'] else 'Completed','failed':'Failed'}.get(run.state,run.state.title())
    elapsed=duration(seconds(run.created_at,run.finished_at or (timezone.now() if run.active_slot else None)))
    return {'run':run,'attempts':attempts,'events':run.events.order_by('-pk')[:50],
        'live_counts':counts,'processed_count':finished,'planned_count':planned,'elapsed':elapsed,
        'current_step':current_step,'state_label':state}


@require_GET
def detail(request, run_id):
    run = get_object_or_404(RobotRun.objects.select_related('dataset__project'), pk=run_id)
    template = 'execution/_progress.html' if request.headers.get('HX-Request') == 'true' else 'execution/detail.html'
    return render(request, template,progress_context(run))


@require_POST
def cancel(request, run_id):
    RobotRun.objects.filter(pk=get_object_or_404(RobotRun, pk=run_id).pk, active_slot='local').update(cancel_requested=True)
    if request.headers.get('HX-Request')=='true':
        run=get_object_or_404(RobotRun,pk=run_id)
        return render(request,'execution/_progress.html',progress_context(run))
    return redirect('run-detail', run_id=run_id)
