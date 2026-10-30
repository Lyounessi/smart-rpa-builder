from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from .models import RobotRun
import json
from django.http import StreamingHttpResponse


def explain_event(run, event):
    context = run.build.confirmed_specification.get('project_context',{}) if run.build else {}
    diagnostic = dict(event.diagnostic)
    target = diagnostic.get('target')
    candidates = context.get('applications',[]) if diagnostic.get('action') == 'navigate' else context.get('captured_elements',[])
    match = next((item for item in candidates if str(item['id']) == target), None)
    if match:
        label = match.get('name') or target
        configured = [step for step in context.get('steps',[]) if target in step.get('element_ids',[])]
        if label in {'div','span','input','button','textarea','select'} and configured:
            label = configured[0]['name']
            if configured[0].get('output_key'):
                label += ' (' + configured[0]['output_key'] + ')'
        diagnostic['target_name'] = label
    name = diagnostic.get('target_name', target or '')
    action = diagnostic.get('action', '')
    if event.kind == 'action_failed':
        elapsed = diagnostic.get('duration_ms',0) / 1000
        reason = 'timed out' if diagnostic.get('exception_type') == 'TimeoutError' else 'failed'
        event.explanation = f'Step “{event.step}”: {action} on “{name}” {reason} after {elapsed:.2f}s ({diagnostic.get("exception_type", "Error")}).'
    else:
        event.explanation = ''
    event.display_diagnostic = diagnostic
    return event


@require_GET
def technical_logs(request, run_id):
    run = get_object_or_404(RobotRun.objects.select_related('build'), pk=run_id)
    def lines():
        for event in run.events.order_by('pk').iterator(chunk_size=200):
            explain_event(run,event)
            yield json.dumps({'timestamp':event.created_at.isoformat(), 'run':str(run.pk),
                'event':event.kind, 'row':event.row_reference, 'step':event.step,
                'diagnostic':event.display_diagnostic, 'explanation':event.explanation}, ensure_ascii=False) + '\n'
    response = StreamingHttpResponse(lines(), content_type='application/x-ndjson')
    response['Content-Disposition'] = f'attachment; filename="run-{run.pk}.jsonl"'
    return response


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
    events = [explain_event(run,event) for event in run.events.order_by('-pk')[:50]]
    failure = run.events.filter(kind='action_failed').order_by('-pk').first()
    return {'run':run,'attempts':attempts,'events':events,
        'failure_summary':explain_event(run,failure).explanation if failure else '',
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
