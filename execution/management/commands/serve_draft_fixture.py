from http.server import ThreadingHTTPServer
from django.core.management.base import BaseCommand
from execution.demo import GreetingHandler


class Command(BaseCommand):
    help = 'Serve the fictional greeting playground on loopback only.'

    def add_arguments(self,parser):
        parser.add_argument('--port',type=int,default=8766)

    def handle(self,*args,**options):
        with ThreadingHTTPServer(('127.0.0.1',options['port']),GreetingHandler) as server:
            self.stdout.write(f'Local greeting playground: http://127.0.0.1:{options["port"]}/')
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
