"""Isolated, deterministic local playground and optional manually authored fixture."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler

from django.db import transaction
from inspector.models import ApplicationWindow, CapturedElement
from projects.models import Project, ProjectInput, WorkflowStep, StepElementReference, Dataset, DatasetRow
from muse_builder.context import create_snapshot
from muse_builder.conversation import confirm_specification
from muse_builder.models import BuildSession
from muse_builder.validation import validate_source
from .models import Robot, RobotBuild

HTML = b'''<!doctype html><html><head><title>Robot greeting playground</title></head><body>
<h1>Local greeting demo</h1><p>Fictional data only. No external services.</p>
<label>Name <input id="name" autocomplete="off"></label><button id="greet">Create greeting</button>
<p id="result" role="status" hidden></p><script>
document.getElementById('greet').onclick=()=>{const result=document.getElementById('result');
result.textContent='Hello, '+document.getElementById('name').value+'!';result.hidden=false;};
</script></body></html>'''


class GreetingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self,*args):
        pass


@transaction.atomic
def prepare_demo(port, *, local_robot=False):
    if Project.objects.filter(name='Greeting draft demo').exists():
        raise ValueError('Greeting draft demo already exists. Existing data was preserved.')
    project = Project.objects.create(name='Greeting draft demo',description='Isolated local Phase 5 demo; fictional data.',
        automation_goal='Fill a name, click Create greeting, and extract the exact greeting for each input row.',
        global_rules='Use only the local playground. No login, email, fixed sleeps or external services.',
        success_criteria='The saved greeting equals Hello, followed by the input name and an exclamation mark, with one space after the comma.')
    definition = ProjectInput.objects.create(project=project,key='name')
    window = ApplicationWindow.objects.create(project=project,name='Local greeting playground',target_url=f'http://127.0.0.1:{port}/')
    elements = {key:CapturedElement.objects.create(window=window,name=key,locator={'strategy':'css','value':'#'+key})
                for key in ['name','greet','result']}
    for index,(name,action,target,instruction) in enumerate([
        ('Enter name','fill','name','Navigate to the local app each row, then fill the captured name field using name.'),
        ('Create greeting','click','greet','Click Create greeting once.'),
        ('Save greeting','read_text','result','Wait for the result, extract greeting, and verify it equals Hello, plus a space, input name and !.')],1):
        step = WorkflowStep.objects.create(project=project,window=window,position=index,name=name,action=action,instruction=instruction,
            input_column=definition if action=='fill' else None,output_key='greeting' if action=='read_text' else '')
        StepElementReference.objects.create(step=step,element=elements[target])
    schema = list(project.inputs.values('key','description','data_type','required'))
    dataset = Dataset.objects.create(project=project,name='Two fictional names',source_name='local demo fixture',
        status='ready',schema_snapshot=schema,headers=['name'],row_count=2)
    DatasetRow.objects.bulk_create([DatasetRow(dataset=dataset,row_number=index,values={'name':name})
        for index,name in enumerate(['Alice','Bob'],2)])
    session = BuildSession.objects.create(project=project,snapshot=create_snapshot(project),manual_reviewed=True,
        decisions={'setup_step_ids':[],'per_row_step_ids':list(project.steps.values_list('pk',flat=True)),
            'stop_on_nok':True,'stop_on_error':True,'success_criteria':project.success_criteria,
            'rejection_handling':'Stop with NOK if the extracted greeting does not exactly match the input name.',
            'recovery_plan':''})
    session = confirm_specification(session)
    build = None
    if local_robot:
        source = f'''from robot_framework.base import BaseRobot
from robot_framework.contracts import BusinessRejection
class ROBOT_GREETING_DRAFT_DEMO(BaseRobot):
    def setup(self, ctx):
        pass
    def process(self, ctx, inputs):
        with ctx.step("fill_name"):
            ctx.navigate({window.pk})
            ctx.fill("{elements['name'].pk}", inputs["name"])
        with ctx.step("greet"):
            ctx.click("{elements['greet'].pk}")
        with ctx.step("save_greeting"):
            ctx.assert_visible("{elements['result'].pk}")
            greeting = ctx.extract_text("{elements['result'].pk}", "greeting")
            if greeting != "Hello, " + inputs["name"] + "!":
                raise BusinessRejection()
'''
        errors = validate_source(source,robot_name='ROBOT_GREETING_DRAFT_DEMO',specification=session.confirmed_specification)
        if errors:
            raise ValueError('Local fixture failed compatibility checks.')
        robot = Robot.objects.create(project=project,name='ROBOT_GREETING_DRAFT_DEMO')
        build = RobotBuild.objects.create(robot=robot,version=1,origin='manual',status='validated',is_draft=True,
            source_files={robot.name+'.py':source},source_digest=sha256(source.encode()).hexdigest(),
            configuration={'robot_name':robot.name,'class_name':robot.name,'execution_enabled':False},
            specification_snapshot=session.snapshot,confirmed_specification=session.confirmed_specification,
            confirmed_specification_hash=session.confirmed_hash,framework_contract_version=session.snapshot.contract_version,
            framework_contract_hash=session.snapshot.contract_hash,
            validation_report=['Manually authored isolated fixture. Static compatibility checks passed; no source was executed during preparation.'])
    return project,dataset,session,build
