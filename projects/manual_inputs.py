"""Transactional dataset row edits, separate from historical execution attempts."""
from hashlib import sha256
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max

from .datasets import MAX_ROWS, MAX_COLUMNS, normalize_value
from .models import Dataset, DatasetRow


def row_revision(row):
    return sha256(json.dumps({'id':row.pk,'dataset':row.dataset_id,'values':row.values,'errors':row.errors,'state':row.processing_status,
        'claimed_by':str(row.claimed_by_id)},sort_keys=True).encode()).hexdigest()


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
            if row_revision(row) != expected_revision:
                raise ValidationError('This input changed since you opened the form. Reload it before saving.')
            if duplicate:
                if row.processing_status != 'done' or row.claimed_by_id:
                    raise ValidationError('Only completed inputs can be duplicated. Wait for the execution to release this input.')
            elif row.processing_status != 'pending' or row.claimed_by_id:
                raise ValidationError('Only pending, unclaimed inputs can be edited.')
        if row is None or duplicate:
            if dataset.rows.count() >= MAX_ROWS:
                raise ValidationError('This MVP supports at most 1,000 inputs per dataset.')
            number = (dataset.rows.aggregate(value=Max('row_number'))['value'] or 1) + 1
            row = DatasetRow.objects.create(dataset=dataset,row_number=number,values=normalized,errors=[],processing_status='pending')
        else:
            row.values,row.errors = normalized,[]
            row.save(update_fields=['values','errors'])
        dataset.row_count = dataset.rows.count()
        dataset.invalid_row_count = dataset.rows.exclude(errors=[]).count()
        dataset.save(update_fields=['row_count','invalid_row_count','updated_at'])
        return row
