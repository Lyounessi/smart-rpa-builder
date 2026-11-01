"""Expose only finalized video artifacts belonging to the selected local run."""
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET

from .models import RobotRun


def recording_path(run, index):
    if run.active_slot or index < 0 or index >= len(run.artifacts):
        return None
    try:
        root = (Path(settings.MEDIA_ROOT) / 'runs' / str(run.pk)).resolve()
        path = Path(run.artifacts[index]).resolve()
        if path.is_relative_to(root) and path.suffix.lower() == '.webm' and path.is_file():
            return path
    except (OSError, ValueError, TypeError):
        pass
    return None


def recordings_for(run):
    return [{'url': reverse('run-recording', args=[run.pk, index]), 'label': f'Recording {index + 1}'}
            for index in range(len(run.artifacts)) if recording_path(run, index)]


@require_GET
def recording(request, run_id, index):
    run = get_object_or_404(RobotRun, pk=run_id)
    path = recording_path(run, index)
    if path is None:
        raise Http404('Recording unavailable.')
    try:
        response = FileResponse(path.open('rb'), content_type='video/webm',
                                as_attachment=request.GET.get('download') == '1', filename=path.name)
    except OSError:
        raise Http404('Recording unavailable.') from None
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
