from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .datasets import parse_dataset, save_preview
from .forms import DatasetUploadForm, ProjectInputForm, ManualDatasetForm, DatasetRowForm, InputActionForm
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
    show_deleted = request.GET.get('deleted')=='1'
    rows = dataset.rows.filter(deleted_at__isnull=not show_deleted)
    page = Paginator(rows, 50).get_page(request.GET.get('page'))
    table = [{'id':row.pk,'number':row.row_number, 'cells':[row.values.get(key, '') for key in dataset.headers], 'errors':row.errors,
        'queue_status':row.get_processing_status_display(), 'editable':row.processing_status=='pending' and not row.claimed_by_id,
        'duplicable':row.processing_status=='done' and not row.claimed_by_id} for row in page]
    current_schema = list(project.inputs.values('key', 'description', 'data_type', 'required'))
    return render(request, 'projects/dataset_detail.html', {'project':project, 'dataset':dataset, 'page':page,
        'table':table,'show_deleted':show_deleted,'deleted_count':dataset.rows.filter(deleted_at__isnull=False).count(),
        'schema_changed':current_schema != dataset.schema_snapshot})


@require_POST
@transaction.atomic
def dataset_confirm(request, project_id, dataset_id):
    project = get_object_or_404(Project, pk=project_id)
    dataset = get_object_or_404(project.datasets.select_for_update(), pk=dataset_id)
    if not dataset.rows.filter(deleted_at__isnull=True).exclude(errors=[]).exists() and dataset.invalid_row_count == 0 and dataset.row_count > 0:
        dataset.status = 'ready'
        dataset.save(update_fields=['status', 'updated_at'])
    return redirect('dataset-detail', project_id=project.pk, dataset_id=dataset.pk)


@require_http_methods(['GET','POST'])
def dataset_create(request,project_id):
    from .models import Dataset
    project = get_object_or_404(Project,pk=project_id)
    schema = list(project.inputs.values('key','description','data_type','required'))
    form = ManualDatasetForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        if not schema or len(schema)>30:
            form.add_error(None,'Define between 1 and 30 project inputs before creating a dataset.')
        else:
            dataset = Dataset.objects.create(project=project,name=form.cleaned_data['name'],source_name='Manual input',
                schema_snapshot=schema,headers=[item['key'] for item in schema],row_count=0,invalid_row_count=0)
            return redirect('dataset-detail',project_id=project.pk,dataset_id=dataset.pk)
    return render(request,'projects/manual_dataset.html',{'project':project,'schema':schema,'form':form})


@require_http_methods(['GET','POST'])
def dataset_row_edit(request,project_id,dataset_id,row_id=None,duplicate=False):
    from .manual_inputs import row_revision,save_input
    project = get_object_or_404(Project,pk=project_id)
    dataset = get_object_or_404(project.datasets,pk=dataset_id)
    row = get_object_or_404(dataset.rows,pk=row_id) if row_id is not None else None
    blocked = ''
    if not dataset.schema_snapshot:
        blocked = 'This dataset has no saved input definitions. Create a new dataset from the project inputs.'
    elif row and (row.deleted_at is not None or row.claimed_by_id or row.processing_status != ('done' if duplicate else 'pending')):
        blocked = 'This input is locked. Edit pending inputs, or duplicate completed inputs once their execution has released them.'
    form = DatasetRowForm(request.POST if request.method=='POST' else None,dataset=dataset,
        values=row.values if row else {},revision=row_revision(row) if row else '')
    if request.method=='POST' and not blocked and form.is_valid():
        try:
            save_input(dataset,form.input_values,row_id=row.pk if row else None,duplicate=duplicate,
                expected_revision=form.cleaned_data['revision'])
        except ValidationError as error:
            form.add_error(None,error)
        else:
            return redirect('dataset-detail',project_id=project.pk,dataset_id=dataset.pk)
    return render(request,'projects/dataset_row_form.html',{'project':project,'dataset':dataset,'form':form,'blocked':blocked,
        'title':'Duplicate completed input' if duplicate else ('Edit pending input' if row else 'Add input')})


@require_GET
def input_detail(request,project_id,input_id):
    project=get_object_or_404(Project,pk=project_id)
    definition=get_object_or_404(project.inputs,pk=input_id)
    return render(request,'projects/input_detail.html',{'project':project,'definition':definition,'steps':definition.steps.all()})


@require_http_methods(['GET','POST'])
def input_delete(request,project_id,input_id):
    from django.db.models.deletion import ProtectedError
    from .manual_inputs import definition_revision,delete_definition
    project=get_object_or_404(Project,pk=project_id)
    definition=get_object_or_404(project.inputs,pk=input_id)
    form=InputActionForm(request.POST if request.method=='POST' else None,initial={'revision':definition_revision(definition)})
    if request.method=='POST' and form.is_valid():
        try:
            delete_definition(definition,expected_revision=form.cleaned_data['revision'])
        except ValidationError as error:
            form.add_error(None,error)
        except ProtectedError:
            form.add_error(None,'This input is used by workflow steps. Remove its mappings before deleting it.')
        else:
            return redirect('project-detail',project_id=project.pk)
    return render(request,'projects/input_delete.html',{'project':project,'definition':definition,'form':form,'steps':definition.steps.all()})


@require_GET
def dataset_row_detail(request,project_id,dataset_id,row_id):
    project=get_object_or_404(Project,pk=project_id)
    dataset=get_object_or_404(project.datasets,pk=dataset_id)
    row=get_object_or_404(dataset.rows,pk=row_id)
    return render(request,'projects/dataset_row_detail.html',{'project':project,'dataset':dataset,'row':row,
        'attempts':row.rowattempt_set.select_related('run').order_by('-created_at')[:20]})


@require_http_methods(['GET','POST'])
def dataset_row_delete(request,project_id,dataset_id,row_id,restore=False):
    from .manual_inputs import row_revision,set_input_deleted
    project=get_object_or_404(Project,pk=project_id)
    dataset=get_object_or_404(project.datasets,pk=dataset_id)
    row=get_object_or_404(dataset.rows,pk=row_id)
    form=InputActionForm(request.POST if request.method=='POST' else None,initial={'revision':row_revision(row)})
    if request.method=='POST' and form.is_valid():
        try:
            set_input_deleted(dataset,row.pk,deleted=not restore,expected_revision=form.cleaned_data['revision'])
        except ValidationError as error:
            form.add_error(None,error)
        else:
            return redirect('dataset-detail',project_id=project.pk,dataset_id=dataset.pk)
    return render(request,'projects/dataset_row_delete.html',{'project':project,'dataset':dataset,'row':row,'form':form,'restore':restore})
