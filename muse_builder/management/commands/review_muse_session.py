from threading import Event, Thread
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from muse_builder.conversation import run_review
from muse_builder.models import BuildOperation


class Command(BaseCommand):
    help = 'Process one queued project clarification operation, outside HTTP handling.'

    def add_arguments(self, parser):
        parser.add_argument('operation_id')

    def handle(self, *args, **options):
        stop = Event()
        def heartbeat():
            close_old_connections()
            try:
                while not stop.wait(5):
                    try:
                        if BuildOperation.objects.filter(pk=options['operation_id'], active_slot='local').update(heartbeat=timezone.now()) != 1:
                            return
                    except Exception:
                        return
            finally:
                close_old_connections()
        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            run_review(options['operation_id'])
        finally:
            stop.set()
            thread.join(timeout=6)
