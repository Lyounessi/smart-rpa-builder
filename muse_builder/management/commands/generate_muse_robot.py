from threading import Event, Thread
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from muse_builder.generation import run_generation
from muse_builder.models import BuildOperation


class Command(BaseCommand):
    help = 'Generate and statically validate a queued draft; never execute generated code.'

    def add_arguments(self, parser):
        parser.add_argument('job_id')

    def handle(self, *args, **options):
        stop = Event()
        def heartbeat():
            close_old_connections()
            try:
                while not stop.wait(5):
                    try:
                        BuildOperation.objects.filter(generation_id=options['job_id'], active_slot='local').update(heartbeat=timezone.now())
                    except Exception:
                        return
            finally:
                close_old_connections()
        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            run_generation(options['job_id'])
        finally:
            stop.set()
            thread.join(timeout=6)
