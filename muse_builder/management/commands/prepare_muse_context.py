from django.core.management.base import BaseCommand, CommandError
from projects.models import Project
from muse_builder.client import MuseError
from muse_builder.context import create_snapshot


class Command(BaseCommand):
    help = 'Save filtered, versioned project context locally. No API call is made.'

    def add_arguments(self, parser):
        parser.add_argument('project_id', type=int)

    def handle(self, *args, **options):
        try:
            snapshot = create_snapshot(Project.objects.get(pk=options['project_id']))
        except Project.DoesNotExist:
            raise CommandError('Project not found.') from None
        except MuseError as error:
            raise CommandError(f'[{error.code}] {error.message}') from None
        self.stdout.write(f'Snapshot: {snapshot.pk}; contract: {snapshot.contract_version}; images: {len(snapshot.images)}.')
        self.stdout.write(f'Specification hash: {snapshot.specification_hash}. No API request made.')
