from django.core.management.base import BaseCommand, CommandError

from muse_builder.client import MuseError
from muse_builder.service import MuseService


class Command(BaseCommand):
    help = 'Make one small, paid Meta API request with a fixed prompt; no project data is sent.'

    def handle(self, *args, **options):
        try:
            result = MuseService().check_connection()
        except MuseError as error:
            raise CommandError(f'[{error.code}] {error.message}') from None
        display = lambda value: 'unavailable' if value is None else str(value)
        self.stdout.write(self.style.SUCCESS(f'Muse connection successful: {result.model} ({result.duration_seconds:.2f}s).'))
        self.stdout.write(f'Tokens: input={display(result.input_tokens)}, output={display(result.output_tokens)}, cached={display(result.cached_tokens)}.')
        self.stdout.write('One request; automatic retries disabled. No project data sent and no robot executed.')
        self.stdout.write(f'Usage ledger: {result.request_id}. Local estimates are not a provider billing guarantee.')
