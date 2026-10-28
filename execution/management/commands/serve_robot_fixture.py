from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from django.core.management.base import BaseCommand

HTML = b'''<!doctype html><title>Local robot fixture</title>
<h1>Fictional invoice checks</h1><div id="login-form">
<label>Username<input id="username" autocomplete="off"></label>
<label>Password<input id="password" type="password"></label><button id="login">Sign in</button></div>
<div id="work" hidden><label>Name<input id="name"></label><button id="submit">Check invoice</button><p id="result" hidden role="status"></p></div>
<script>
document.getElementById('login').onclick=()=>{
 if(document.getElementById('username').value==='demo' && document.getElementById('password').value==='demo'){
 document.getElementById('login-form').hidden=true;document.getElementById('work').hidden=false;}};
document.getElementById('submit').onclick=()=>{let result=document.getElementById('result');
result.textContent=document.getElementById('name').value==='Reject'?'Rejected':'Accepted';result.hidden=false;};
</script>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *args):
        pass


class Command(BaseCommand):
    help = 'Serve the deterministic, fictional browser fixture on loopback only.'

    def add_arguments(self, parser):
        parser.add_argument('--port', type=int, default=8765)

    def handle(self, *args, **options):
        with ThreadingHTTPServer(('127.0.0.1', options['port']), Handler) as server:
            self.stdout.write('Local fixture ready. Fictional username/password: demo / demo.')
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
