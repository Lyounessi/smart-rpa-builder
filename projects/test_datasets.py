import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .datasets import parse_dataset
from .models import Dataset, DatasetRow, Project, ProjectInput


class DatasetTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Invoice workflow')
        self.other = Project.objects.create(name='Other workflow')
        self.text = ProjectInput.objects.create(project=self.project, key='name', description='Customer name')
        self.number = ProjectInput.objects.create(project=self.project, key='amount', data_type='number', required=False)

    def schema(self):
        return list(self.project.inputs.values('key', 'description', 'data_type', 'required'))

    def csv(self, value):
        return SimpleUploadedFile('input.csv', value.encode('utf-8'))

    def xlsx(self, rows, extra_sheet=False):
        from openpyxl import Workbook
        workbook = Workbook()
        for row in rows:
            workbook.active.append(row)
        if extra_sheet:
            workbook.create_sheet('Extra')
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        return SimpleUploadedFile('input.xlsx', output.getvalue())

    def upload(self, file):
        return self.client.post(reverse('dataset-upload', args=[self.project.pk]), {'name':'October records', 'file':file})

    def test_define_edit_inputs_and_reject_duplicates(self):
        url = reverse('input-create', args=[self.project.pk])
        self.assertEqual(self.client.post(url, {'key':'document_type', 'description':'Type', 'data_type':'text', 'required':'on'}).status_code, 302)
        self.assertContains(self.client.post(url, {'key':'name', 'data_type':'text'}), 'already has an input')
        self.assertContains(self.client.post(url, {'key':'Invalid Key', 'data_type':'text'}), 'Use lowercase letters')
        url = reverse('input-edit', args=[self.project.pk, self.text.pk])
        self.assertEqual(self.client.post(url, {'key':'name', 'description':'Updated', 'data_type':'text', 'required':'on'}).status_code, 302)
        self.text.refresh_from_db()
        self.assertEqual(self.text.description, 'Updated')
        self.assertEqual(self.client.get(reverse('input-edit', args=[self.other.pk, self.text.pk])).status_code, 404)

    def test_csv_preview_confirm_and_retrieve(self):
        response = self.upload(self.csv('\ufeffamount,name\n12.50,Alice\n,Bob\n'))
        dataset = Dataset.objects.get(project=self.project)
        self.assertRedirects(response, reverse('dataset-detail', args=[self.project.pk, dataset.pk]))
        self.assertEqual(dataset.headers, ['amount', 'name'])
        self.assertEqual(dataset.row_count, 2)
        self.assertEqual(dataset.status, 'preview')
        self.assertEqual(dataset.rows.first().values, {'amount':'12.50', 'name':'Alice'})
        self.client.post(reverse('dataset-confirm', args=[self.project.pk, dataset.pk]))
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, 'ready')
        self.assertContains(self.client.get(reverse('dataset-detail', args=[self.project.pk, dataset.pk])), 'Alice')

    def test_invalid_rows_are_visible_and_cannot_be_confirmed(self):
        self.upload(self.csv('name,amount\n,12\nAlice,NaN\nBob,abc\n'))
        dataset = Dataset.objects.get()
        self.assertEqual(dataset.invalid_row_count, 3)
        response = self.client.get(reverse('dataset-detail', args=[self.project.pk, dataset.pk]))
        self.assertContains(response, 'required value is missing')
        self.assertContains(response, 'finite number')
        self.client.post(reverse('dataset-confirm', args=[self.project.pk, dataset.pk]))
        dataset.refresh_from_db()
        self.assertEqual(dataset.status, 'preview')

    def test_headers_and_bad_files_do_not_persist_partial_datasets(self):
        for text in ['', 'name,name\nAlice,Bob', 'unknown,amount\nAlice,1', 'name,amount\nAlice,1,extra', 'name,amount\n']:
            with self.subTest(text=text):
                response = self.upload(self.csv(text))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(Dataset.objects.exists())
        self.assertEqual(self.upload(SimpleUploadedFile('file.xlsx', b'not an xlsx')).status_code, 200)
        self.assertFalse(DatasetRow.objects.exists())

    def test_xlsx_parses_values_and_rejects_formulas_and_extra_sheets(self):
        headers, rows = parse_dataset(self.xlsx([['name', 'amount'], ['Alice', 12.5], ['Bob', None]]), self.schema())
        self.assertEqual(headers, ['name', 'amount'])
        self.assertEqual(rows[0]['values']['amount'], '12.5')
        self.assertEqual(rows[1]['values']['amount'], '')
        for file in [self.xlsx([['name', 'amount'], ['Alice', '=1+1']]), self.xlsx([['name', 'amount'], ['Alice', 1]], extra_sheet=True)]:
            with self.assertRaises(ValidationError):
                parse_dataset(file, self.schema())

    def test_text_identifiers_and_decimal_precision_are_preserved(self):
        _, rows = parse_dataset(self.csv('name,amount\n00123,1234567890.12345678901234567890\n'), self.schema())
        self.assertEqual(rows[0]['values']['name'], '00123')
        self.assertEqual(rows[0]['values']['amount'], '1234567890.12345678901234567890')

    def test_file_size_row_and_cell_limits(self):
        for file in [SimpleUploadedFile('large.csv', b'x' * (2*1024*1024+1)), self.csv('name,amount\n' + 'Alice,1\n'*1001), self.csv('name,amount\n'+'x'*2001+',1')]:
            with self.assertRaises(ValidationError):
                parse_dataset(file, self.schema())

    def test_old_dataset_keeps_input_snapshot_and_is_project_scoped(self):
        self.upload(self.csv('name,amount\nAlice,1\n'))
        dataset = Dataset.objects.get()
        self.text.key = 'customer_name'
        self.text.save()
        response = self.client.get(reverse('dataset-detail', args=[self.project.pk, dataset.pk]))
        self.assertContains(response, 'Project inputs have changed')
        self.assertEqual(dataset.schema_snapshot[0]['key'], 'name')
        self.assertEqual(self.client.get(reverse('dataset-detail', args=[self.other.pk, dataset.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('dataset-confirm', args=[self.other.pk, dataset.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('dataset-confirm', args=[self.project.pk, dataset.pk])).status_code, 405)

    def test_pagination_and_escaped_preview_values(self):
        self.upload(self.csv('name,amount\n' + '<script>alert(1)</script>,1\n'*51))
        dataset = Dataset.objects.get()
        response = self.client.get(reverse('dataset-detail', args=[self.project.pk, dataset.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')
        self.assertEqual(len(response.context['table']), 50)
        self.assertEqual(len(self.client.get(reverse('dataset-detail', args=[self.project.pk, dataset.pk]), {'page':2}).context['table']), 1)

    def test_upload_requires_definitions_and_utf8(self):
        with self.assertRaises(ValidationError):
            parse_dataset(self.csv('name\nAlice'), [])
        with self.assertRaises(ValidationError):
            parse_dataset(SimpleUploadedFile('input.csv', b'name,amount\n\xff,1'), self.schema())
