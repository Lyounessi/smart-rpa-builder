import csv
from io import BytesIO

from django.http import FileResponse, Http404, HttpResponse
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell


def download_results(file_format, filename, records):
    if file_format == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.write('﻿')
        writer = csv.writer(response)
        for record in records:
            # Spreadsheet apps may evaluate formula-like text in CSV.
            writer.writerow([
                "'" + value if isinstance(value, str) and (
                    value.startswith(('\t', '\r', '\n')) or
                    value.lstrip().startswith(('=', '+', '-', '@'))
                ) else value for value in record
            ])
        return response
    if file_format == 'xlsx':
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet('Results')
        for record in records:
            cells = []
            for value in record:
                cell = WriteOnlyCell(sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = 's'
                cells.append(cell)
            sheet.append(cells)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename=filename)
    raise Http404


def output_records(attempts):
    yield ['Scope', 'Dataset', 'Run ID', 'Record', 'Outcome', 'Output', 'Value']
    exported_runs = set()
    for attempt in attempts:
        run = attempt.run
        reference = [run.dataset.name, str(run.pk)]
        for key, value in (attempt.outputs or {'': ''}).items():
            yield ['Record', *reference, attempt.row.row_number, attempt.outcome, key, value]
        if run.pk not in exported_runs:
            for key, value in run.outputs.items():
                yield ['Run', *reference, '', run.state, key, value]
            exported_runs.add(run.pk)
