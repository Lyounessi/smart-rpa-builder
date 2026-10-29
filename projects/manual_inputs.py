"""Transactional dataset row edits, separate from historical execution attempts."""
from hashlib import sha256
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .datasets import MAX_ROWS, MAX_COLUMNS, normalize_value
from .models import Dataset, DatasetRow, ProjectInput


def definition_revision(definition):
    fields = ['id','project_id','key','description','data_type','required']
    return sha256(json.dumps({key:getattr(definition,key) for key in fields},sort_keys=True).encode()).hexdigest()


def delete_definition(definition,*,expected_revision):
    with transaction.atomic():
        ProjectInput.objects.filter(pk=definition.pk).update(key=F('key'))
        definition = ProjectInput.objects.select_for_update().get(pk=definition.pk)
        if definition_revision(definition)!=expected_revision:
            raise ValidationError('This input definition changed. Reload before deleting it.')
        if definition.steps.exists():
            raise ValidationError('This input is used by workflow steps. Remove or change those mappings before deleting it.')
        definition.delete()


def row_revision(row):
    return sha256(json.dumps({'id':row.pk,'dataset':row.dataset_id,'values':row.values,'errors':row.errors,'state':row.processing_status,
        'claimed_by':str(row.claimed_by_id),'deleted_at':str(row.deleted_at)},sort_keys=True).encode()).hexdigest()


def update_counts(dataset):
    active = dataset.rows.filter(deleted_at__isnull=True)
    dataset.row_count = active.count()
    dataset.invalid_row_count = active.exclude(errors=[]).count()
    if not dataset.row_count or dataset.invalid_row_count:
        dataset.status = 'preview'
    dataset.save(update_fields=['row_count','invalid_row_count','status','updated_at'])


def set_input_deleted(dataset,row_id,*,deleted,expected_revision):
    with transaction.atomic():
        Dataset.objects.filter(pk=dataset.pk).update(row_count=F('row_count'))
        dataset = Dataset.objects.select_for_update().get(pk=dataset.pk)
        row = DatasetRow.objects.select_for_update().get(pk=row_id,dataset=dataset)
        if row_revision(row) != expected_revision:
            raise ValidationError('This input changed. Reload the page before continuing.')
        if row.claimed_by_id or row.processing_status=='in_progress' or dataset.runs.filter(active_slot='local').exists():
            raise ValidationError('Stop the active dataset execution before deleting or restoring inputs.')
        if deleted == (row.deleted_at is not None):
            raise ValidationError('This input is already deleted.' if deleted else 'This input is already active.')
        if not deleted and dataset.rows.filter(deleted_at__isnull=True).count()>=MAX_ROWS:
            raise ValidationError('This dataset already has 1,000 active inputs.')
        row.deleted_at = timezone.now() if deleted else None
        row.save(update_fields=['deleted_at'])
        update_counts(dataset)
        return row


def save_input(dataset,values,*,row_id=None,duplicate=False,expected_revision=''):
    with transaction.atomic():
        # Write first: serialize row numbering and avoid SQLite read-to-write races.
        Dataset.objects.filter(pk=dataset.pk).update(row_count=F('row_count'))
        dataset = Dataset.objects.select_for_update().get(pk=dataset.pk)
        schema = dataset.schema_snapshot
        if not schema or len(schema)>MAX_COLUMNS or set(values) != {item['key'] for item in schema}:
            raise ValidationError('Use the input definitions saved with this dataset.')
        normalized = {}
        for definition in schema:
            value,error = normalize_value(values[definition['key']],definition)
            if error:
                raise ValidationError(error)
            normalized[definition['key']] = value
        row = None
        if row_id is not None:
            row = DatasetRow.objects.select_for_update().get(pk=row_id,dataset=dataset)
            if row.deleted_at is not None:
                raise ValidationError('Restore this deleted input before editing or duplicating it.')
            if row_revision(row) != expected_revision:
                raise ValidationError('This input changed since you opened the form. Reload it before saving.')
            if duplicate:
                if row.processing_status != 'done' or row.claimed_by_id:
                    raise ValidationError('Only completed inputs can be duplicated. Wait for the execution to release this input.')
            elif row.processing_status != 'pending' or row.claimed_by_id:
                raise ValidationError('Only pending, unclaimed inputs can be edited.')
        if row is None or duplicate:
            if dataset.rows.filter(deleted_at__isnull=True).count() >= MAX_ROWS:
                raise ValidationError('This MVP supports at most 1,000 inputs per dataset.')
            number = (dataset.rows.aggregate(value=Max('row_number'))['value'] or 1) + 1
            row = DatasetRow.objects.create(dataset=dataset,row_number=number,values=normalized,errors=[],processing_status='pending')
        else:
            row.values,row.errors = normalized,[]
            row.save(update_fields=['values','errors'])
        update_counts(dataset)
        return row
