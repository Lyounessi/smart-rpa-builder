from django.core.management.base import BaseCommand
from execution.draft_tests import execute_test


class Command(BaseCommand):
    help = 'Execute one queued, explicitly reviewed draft test. No generation or activation.'

    def add_arguments(self, parser):
        parser.add_argument('run_id')

    def handle(self, *args, **options):
        execute_test(options['run_id'])
