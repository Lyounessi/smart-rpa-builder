from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from .models import RobotRun


@require_GET
def detail(request, run_id):
    run = get_object_or_404(RobotRun.objects.select_related('dataset__project'), pk=run_id)
    template = 'execution/_progress.html' if request.headers.get('HX-Request') == 'true' else 'execution/detail.html'
    return render(request, template, {'run': run, 'attempts': run.attempts.select_related('row').prefetch_related('actions').order_by('pk'),
        'events': run.events.order_by('-pk')[:50]})


@require_POST
def cancel(request, run_id):
    RobotRun.objects.filter(pk=get_object_or_404(RobotRun, pk=run_id).pk, active_slot='local').update(cancel_requested=True)
    return redirect('run-detail', run_id=run_id)
