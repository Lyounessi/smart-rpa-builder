from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db import IntegrityError

from inspector.models import CapturedElement
from projects.models import Dataset
from robot_framework.adapters.browser import PlaywrightBrowser
from robot_framework.adapters.secrets import EnvironmentSecrets
from robot_framework.contracts import RunOptions
from robot_framework.runner import Runner
from robots.registry import for_project
from execution.adapters import DjangoQueue, LeaseCancellation, create_run


class Command(BaseCommand):
    help = 'Execute a trusted named robot against pending rows of a confirmed dataset.'

    def add_arguments(self, parser):
        parser.add_argument('robot_name')
        parser.add_argument('--dataset', type=int, required=True)
        parser.add_argument('--record-screen', action='store_true', help='Record browser page video (sensitive).')
        parser.add_argument('--stop-on-nok', action='store_true')
        parser.add_argument('--continue-on-error', action='store_true')
        parser.add_argument('--action-timeout-ms', type=int, default=10000)

    def handle(self, *args, **options):
        try:
            dataset = Dataset.objects.select_related('project').get(pk=options['dataset'])
            registry = for_project(dataset.project)
            registry.resolve(options['robot_name'])
            run_options = RunOptions(options['record_screen'], options['stop_on_nok'],
                not options['continue_on_error'], options['action_timeout_ms'])
            run = create_run(dataset, options['robot_name'])
        except (ValueError, ObjectDoesNotExist, MultipleObjectsReturned, IntegrityError) as error:
            raise CommandError('Cannot start: invalid robot/dataset/options, or another run is active.') from error
        self.stdout.write(f'Run {run.pk}: /execution/{run.pk}/')
        queue = DjangoQueue(run)
        elements = {str(element.pk): element.locator for element in CapturedElement.objects.filter(window__project=dataset.project)}
        applications = {str(window.pk): window.target_url for window in dataset.project.windows.all()}
        browser = PlaywrightBrowser(elements, applications, Path(settings.MEDIA_ROOT) / 'runs' / str(run.pk))
        try:
            with LeaseCancellation(run.pk) as cancellation:
                result = Runner(registry, browser, EnvironmentSecrets(), queue, cancellation).run(
                    options['robot_name'], queue.rows(), run_options)
        except Exception:
            raise CommandError('Worker could not persist progress. Lease recovery will release abandoned work; review before retrying.') from None
        self.stdout.write(f'{result.state}: {len(result.rows)} rows attempted.')
        if result.state in {'failed', 'cancelled'}:
            raise CommandError('Run did not complete. Review the progress page.')
