from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .datasets import parse_dataset, save_preview
from .forms import DatasetUploadForm, ProjectInputForm
from .models import Project
from .views import form_response, successful_save


@require_http_methods(['GET', 'POST'])
def input_edit(request, project_id, input_id=None):
    project = get_object_or_404(Project, pk=project_id)
    definition = get_object_or_404(project.inputs, pk=input_id) if input_id else None
    form = ProjectInputForm(request.POST if request.method == 'POST' else None, project=project, instance=definition)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return successful_save(request, project)
    return form_response(request, form, 'Edit project input' if definition else 'Add project input', project)


@require_http_methods(['GET', 'POST'])
def dataset_upload(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    schema = list(project.inputs.values('key', 'description', 'data_type', 'required'))
    form = DatasetUploadForm(request.POST if request.method == 'POST' else None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            upload = form.cleaned_data['file']
            headers, records = parse_dataset(upload, schema)
            # Keep only the display filename and parsed data, never the original upload.
            filename = PurePosixPath(upload.name.replace('\\', '/')).name[:255]
            dataset = save_preview(project, form.cleaned_data['name'], filename, schema, headers, records)
        except ValidationError as error:
            form.add_error('file', error)
        else:
            return redirect('dataset-detail', project_id=project.pk, dataset_id=dataset.pk)
    return render(request, 'projects/dataset_upload.html', {'project':project, 'form':form, 'schema':schema})


@require_GET
def dataset_detail(request, project_id, dataset_id):
    project = get_object_or_404(Project, pk=project_id)
    dataset = get_object_or_404(project.datasets, pk=dataset_id)
    page = Paginator(dataset.rows.all(), 50).get_page(request.GET.get('page'))
    table = [{'number':row.row_number, 'cells':[row.values.get(key, '') for key in dataset.headers], 'errors':row.errors} for row in page]
    current_schema = list(project.inputs.values('key', 'description', 'data_type', 'required'))
    return render(request, 'projects/dataset_detail.html', {'project':project, 'dataset':dataset, 'page':page,
        'table':table, 'schema_changed':current_schema != dataset.schema_snapshot})


@require_POST
@transaction.atomic
def dataset_confirm(request, project_id, dataset_id):
    project = get_object_or_404(Project, pk=project_id)
    dataset = get_object_or_404(project.datasets.select_for_update(), pk=dataset_id)
    if not dataset.rows.exclude(errors=[]).exists() and dataset.invalid_row_count == 0 and dataset.row_count > 0:
        dataset.status = 'ready'
        dataset.save(update_fields=['status', 'updated_at'])
    return redirect('dataset-detail', project_id=project.pk, dataset_id=dataset.pk)
