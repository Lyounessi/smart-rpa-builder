from django.core.management.base import BaseCommand, CommandError
from execution.demo import prepare_demo


class Command(BaseCommand):
    help = 'Prepare a new local greeting project, confirmed specification and two fictional input rows.'

    def add_arguments(self, parser):
        parser.add_argument('--port',type=int,default=8766)
        parser.add_argument('--local-robot',action='store_true',help='Also create a manually authored draft fixture; no API call.')

    def handle(self,*args,**options):
        if not 1024 <= options['port'] <= 65535:
            raise CommandError('Choose a local port from 1024 to 65535.')
        try:
            project,dataset,session,build = prepare_demo(options['port'],local_robot=options['local_robot'])
        except ValueError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(f'Project {project.pk}; dataset {dataset.pk}; confirmed session {session.pk}; build {build.pk if build else "not generated"}. No API call made.')
