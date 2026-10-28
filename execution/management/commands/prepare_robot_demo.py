from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from inspector.models import ApplicationWindow, CapturedElement
from projects.models import Project, ProjectInput, Dataset, DatasetRow


class Command(BaseCommand):
    help = 'Create an isolated fictional Invoice Checks project, targets, and two ready rows.'

    def add_arguments(self, parser):
        parser.add_argument('--port', type=int, default=8765)
        parser.add_argument('--with-email', action='store_true', help='Create a separate fictional email demo; use --fake-email at execution.')

    @transaction.atomic
    def handle(self, *args, **options):
        project_name = 'Invoice Checks Email' if options['with_email'] else 'Invoice Checks'
        if Project.objects.filter(name=project_name).exists():
            raise CommandError('Demo project already exists; nothing was changed.')
        project = Project.objects.create(name=project_name, description='Isolated framework fixture, fictional data only.')
        definition = ProjectInput.objects.create(project=project, key='name')
        window = ApplicationWindow.objects.create(project=project, name='Local robot fixture', target_url=f'http://127.0.0.1:{options["port"]}/')
        for alias in ['username', 'password', 'login', 'name', 'submit', 'result']:
            CapturedElement.objects.create(window=window, name=alias, locator={'strategy':'css', 'value':'#' + alias})
        if options['with_email']:
            ProjectInput.objects.create(project=project, key='email')
        schema = list(project.inputs.values('key', 'description', 'data_type', 'required'))
        dataset = Dataset.objects.create(project=project, name='Fictional two-row test', source_name='generated fixture',
            schema_snapshot=schema, headers=[item['key'] for item in schema], status='ready', row_count=2)
        DatasetRow.objects.bulk_create([DatasetRow(dataset=dataset, row_number=index,
            values={'name':name, **({'email':f'fictional-{index}@example.invalid'} if options['with_email'] else {})})
            for index, name in enumerate(['Fictional Alice', 'Fictional Bob'], start=2)])
        from robot_framework.registry import robot_name
        flag = ' --fake-email' if options['with_email'] else ''
        self.stdout.write(f'Dataset {dataset.pk}. Run: python manage.py run_robot {robot_name(project.name)} --dataset {dataset.pk}{flag}')
