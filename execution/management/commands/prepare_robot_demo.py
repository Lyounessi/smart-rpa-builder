from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from inspector.models import ApplicationWindow, CapturedElement
from projects.models import Project, ProjectInput, Dataset, DatasetRow


class Command(BaseCommand):
    help = 'Create an isolated fictional Invoice Checks project, targets, and two ready rows.'

    def add_arguments(self, parser):
        parser.add_argument('--port', type=int, default=8765)

    @transaction.atomic
    def handle(self, *args, **options):
        if Project.objects.filter(name='Invoice Checks').exists():
            raise CommandError('Invoice Checks already exists; nothing was changed.')
        project = Project.objects.create(name='Invoice Checks', description='Isolated framework fixture, fictional data only.')
        definition = ProjectInput.objects.create(project=project, key='name')
        window = ApplicationWindow.objects.create(project=project, name='Local robot fixture', target_url=f'http://127.0.0.1:{options["port"]}/')
        for alias in ['username', 'password', 'login', 'name', 'submit', 'result']:
            CapturedElement.objects.create(window=window, name=alias, locator={'strategy':'css', 'value':'#' + alias})
        dataset = Dataset.objects.create(project=project, name='Fictional two-row test', source_name='generated fixture',
            schema_snapshot=[{'key':definition.key, 'description':'', 'data_type':'text', 'required':True}],
            headers=['name'], status='ready', row_count=2)
        DatasetRow.objects.bulk_create([DatasetRow(dataset=dataset, row_number=index, values={'name':name})
            for index, name in enumerate(['Fictional Alice', 'Fictional Bob'], start=2)])
        self.stdout.write(f'Dataset {dataset.pk}. Run: python manage.py run_robot ROBOT_INVOICE_CHECKS --dataset {dataset.pk}')
