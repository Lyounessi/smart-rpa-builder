from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from execution.models import RobotBuild, RobotRun
from execution.draft_tests import queue_test, execute_test
from projects.models import Dataset


class Command(BaseCommand):
    help = 'Test a reviewed draft on 1–5 pending rows. Source runs with local Python permissions.'

    def add_arguments(self, parser):
        parser.add_argument('build_id',type=int)
        parser.add_argument('--dataset',type=int,required=True)
        parser.add_argument('--reviewed-source-digest',required=True)
        parser.add_argument('--row-limit',type=int,default=2)
        parser.add_argument('--record-screen',action='store_true')

    def handle(self, *args, **options):
        try:
            build = RobotBuild.objects.select_related('robot','specification_snapshot').get(pk=options['build_id'])
            run = queue_test(build,Dataset.objects.get(pk=options['dataset']),
                reviewed_digest=options['reviewed_source_digest'],acknowledged=True,
                row_limit=options['row_limit'],record_screen=options['record_screen'])
        except (ValueError,KeyError,ObjectDoesNotExist,IntegrityError):
            raise CommandError('Cannot queue test. Check draft review, dataset, row limit, source fingerprint and active runs.') from None
        self.stdout.write(f'Test run {run.pk}: /execution/{run.pk}/')
        execute_test(run.pk)
        run.refresh_from_db()
        self.stdout.write(f'{run.state}: {run.counts}')
        if run.state != 'completed':
            raise CommandError('Test did not complete. Review its saved progress and results.')
