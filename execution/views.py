from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from .models import RobotRun, ProgressEvent
import json
from django.http import StreamingHttpResponse


def explain_event(run, event, prior_click=None):
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
        if action in {'assert_visible','read_text','read_value','wait_for_progress'}:
            if prior_click is None:
                prior_click=run.events.filter(pk__lt=event.pk,kind='action_completed',step=event.step,
                    row_reference=event.row_reference,diagnostic__action='click').exists()
            if prior_click:
                event.explanation += ' The click completed, but its subsequent success check failed. The external outcome is unconfirmed; check the application before retrying.'
                diagnostic['failure_stage']='verification_after_click'
    else:
        event.explanation = ''
    event.display_diagnostic = diagnostic
    return event


def explain_attempts(attempts):
    """Attach readable failure evidence without rewriting historical attempt outcomes."""
    attempts=list(attempts)
    if not attempts:
        return
    runs={item.run_id:item.run for item in attempts}
    events=ProgressEvent.objects.filter(run_id__in=runs,row_reference__in=[str(a.row_id) for a in attempts],
        kind__in=['action_completed','action_failed']).order_by('pk')
    clicked,last_failure=set(),{}
    for event in events:
        key=(event.run_id,event.row_reference,event.step)
        if event.kind=='action_completed' and event.diagnostic.get('action')=='click':
            clicked.add(key)
        elif event.kind=='action_failed':
            last_failure[(event.run_id,event.row_reference)]=explain_event(runs[event.run_id],event,key in clicked).explanation
    for attempt in attempts:
        attempt.diagnostic_summary=last_failure.get((attempt.run_id,str(attempt.row_id)),'')


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
    from .recordings import recordings_for
    attempts=list(run.attempts.select_related('row').prefetch_related('actions').order_by('pk'))
    for attempt in attempts:
        attempt.run=run
    explain_attempts(attempts)
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
    treated=sum(item.business_completed_at is not None or item.outcome == 'OK' for item in attempts)
    return {'run':run,'attempts':attempts,'events':events,'recordings':recordings_for(run),
        'treated_count':treated, 'remaining_count':max(0,planned-treated) if planned is not None else len(run.unprocessed),
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
