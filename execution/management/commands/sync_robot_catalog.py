from django.core.management.base import BaseCommand
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from projects.models import Project
from execution.catalog import register_manual_build
from robot_framework.registry import robot_name


class Command(BaseCommand):
    help = 'Register existing trusted manual demo robots without running or creating projects.'

    def handle(self, *args, **options):
        count = 0
        for project in Project.objects.filter(name__in=['Invoice Checks', 'Invoice Checks Email']):
            try:
                register_manual_build(project, robot_name(project.name))
            except (ValueError, ObjectDoesNotExist, MultipleObjectsReturned):
                self.stdout.write(f'Project {project.pk}: trusted fixture configuration is incomplete.')
            else:
                count += 1
        self.stdout.write(f'{count} manual robot(s) registered. No robots executed.')
