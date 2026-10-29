from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from muse_builder.budget import close_abandoned
from muse_builder.client import MuseError
from muse_builder.models import MuseRequest


class Command(BaseCommand):
    help = 'After stopping an abandoned worker, close its active slot while retaining the full monetary reservation.'

    def add_arguments(self, parser):
        parser.add_argument('request_id', type=str)
        parser.add_argument('--worker-stopped', action='store_true')

    def handle(self, *args, **options):
        if not options['worker_stopped']:
            raise CommandError('Stop/verify the owning worker first, then pass --worker-stopped. This does not cancel a provider request.')
        try:
            request = close_abandoned(options['request_id'])
        except (MuseRequest.DoesNotExist, ValueError, ValidationError, MuseError):
            raise CommandError('Request not found or already finalized.') from None
        self.stdout.write(f'Request {request.pk} closed as uncertain. Full reservation retained; no API call made.')
