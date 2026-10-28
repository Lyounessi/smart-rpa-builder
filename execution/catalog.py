"""Snapshot trusted local implementations. No generated code is imported here."""
import hashlib
import json

from django.conf import settings
from django.db import transaction

from robots.registry import for_project
from robot_framework.registry import robot_name
from .models import Robot, RobotBuild


@transaction.atomic
def register_manual_build(project, name):
    registry = for_project(project)
    implementation = registry.resolve(name)
    if name != robot_name(project.name):
        raise ValueError('Robot name does not match this project.')
    robot, _ = Robot.objects.get_or_create(project=project, defaults={'name':name})
    # Serialize allocation on databases with row locking. The unique version key
    # also protects SQLite; a competing registration may need to be retried by its caller.
    Robot.objects.select_for_update().get(pk=robot.pk)
    files = [*sorted((settings.BASE_DIR / 'robot_framework').glob('*.py')),
             *sorted((settings.BASE_DIR / 'robot_framework' / 'adapters').glob('*.py')),
             settings.BASE_DIR / 'robots' / 'registry.py', settings.BASE_DIR / 'robots' / 'example_robot.py']
    if project.name == 'Invoice Checks Email':
        files.append(settings.BASE_DIR / 'robots' / 'email_example_robot.py')
    sources = {path.relative_to(settings.BASE_DIR).as_posix(): path.read_text(encoding='utf-8')
               for path in files if not path.name.startswith('test')}
    configuration = {
        'robot_name':name,
        'element_bindings':implementation.elements,
        'applications':{str(window.pk):window.target_url for window in project.windows.all()},
        'elements':{str(element.pk):element.locator for window in project.windows.all() for element in window.elements.all()},
    }
    digest = hashlib.sha256(json.dumps({'sources':sources, 'configuration':configuration}, sort_keys=True).encode()).hexdigest()
    latest = robot.builds.first()
    if latest and latest.source_digest == digest:
        return latest
    return RobotBuild.objects.create(robot=robot, version=latest.version + 1 if latest else 1,
        origin='manual', status='registered', source_files=sources, configuration=configuration,
        source_digest=digest, validation_report=['Trusted manual registry entry; no Muse generation or automated build validation performed.'])
