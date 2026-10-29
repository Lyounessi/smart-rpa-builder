from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from muse_builder.budget import close_abandoned
from muse_builder.client import MuseError
from muse_builder.conversation import fail_operation
from muse_builder.models import BuildOperation, MuseRequest


class Command(BaseCommand):
    help = 'After stopping a review worker, close its local slots without refunding uncertain usage.'

    def add_arguments(self, parser):
        parser.add_argument('operation_id')
        parser.add_argument('--worker-stopped', action='store_true')

    def handle(self, *args, **options):
        if not options['worker_stopped']:
            raise CommandError('Stop/verify the owning worker, then pass --worker-stopped. This does not cancel provider work.')
        try:
            operation = BuildOperation.objects.get(pk=options['operation_id'], active_slot='local')
            request = MuseRequest.objects.filter(build_operation=operation, active_slot='local').first()
            if request:
                close_abandoned(request.pk)
            message = 'Worker stopped. Uncertain API reservations were retained; no automatic retry was made.'
            if operation.generation_id:
                from muse_builder.generation import fail_generation
                fail_generation(operation.generation_id, message)
            else:
                fail_operation(operation.pk, message)
        except (BuildOperation.DoesNotExist, ValueError, ValidationError, MuseError):
            raise CommandError('Review not found or already finalized.') from None
        self.stdout.write('Review closed. No API call made; uncertain charges were retained.')
