"""Restricted static compatibility checks. Never import or execute generated code."""
import ast
import re
from robot_framework.email import referenced_fields
from .generation_schema import MAX_SOURCE_BYTES

IMPORTS = {'robot_framework.base':{'BaseRobot'},
           'robot_framework.contracts':{'BusinessRejection','TechnicalError','ExecutionCancelled','Outcome'},
           'robot_framework.email':{'EmailStep'}}
ACTIONS = {'fill','click','select_option','read_text','assert_visible','navigate','step','checkpoint','business_completed'}
BUILTINS = {'str','int','float','bool','len','min','max','round','isinstance','list','dict','tuple','set','all','any'}
STRING_METHODS = {'strip','lower','upper','casefold','replace','startswith','endswith','get','items','values','keys'}
UNKNOWN = object()


def validate_source(source, *, robot_name, specification):
    errors = []
    def fail(node, message):
        errors.append(f'Line {getattr(node,"lineno",1)}: {message}')
    if not source.strip() or len(source.encode('utf-8')) > MAX_SOURCE_BYTES:
        return ['Source must be nonempty and at most 64 KB.']
    try:
        tree = ast.parse(source)
        if sum(1 for _ in ast.walk(tree)) > 8000:
            return ['Source exceeds the AST complexity limit.']
    except (SyntaxError,ValueError,RecursionError,MemoryError) as error:
        return [f'Line {getattr(error,"lineno",1)}: source is not valid supported Python syntax.']
    imports = {}
    classes = []
    for node in tree.body:
        if isinstance(node,ast.ImportFrom):
            for item in node.names:
                if node.level or item.name not in IMPORTS.get(node.module,set()):
                    fail(node,'Import is outside the supported framework contract.')
                else:
                    imports[item.asname or item.name] = item.name
        elif isinstance(node,ast.ClassDef):
            classes.append(node)
        elif not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)):
            fail(node,'Only framework imports, a docstring and one robot class are allowed at module level.')
    if len(classes) != 1:
        return errors + ['Define exactly one robot class.']
    cls = classes[0]
    if cls.name != robot_name or len(cls.bases) != 1 or not isinstance(cls.bases[0],ast.Name) or imports.get(cls.bases[0].id) != 'BaseRobot':
        fail(cls,'Use the exact requested robot class name and BaseRobot base class.')
    if cls.decorator_list or cls.keywords:
        fail(cls,'Class decorators and metaclasses are unsupported.')
    methods, constants = {}, {}
    for node in cls.body:
        if isinstance(node,ast.FunctionDef):
            if node.name in methods:
                fail(node,'Duplicate methods are unsupported.')
            methods[node.name] = node
        elif isinstance(node,ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0],ast.Name):
            constants[node.targets[0].id] = node.value
        elif not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)):
            fail(node,'Class body must contain methods or fixed constants only.')

    def resolve(node, env, depth=0):
        if depth > 20:
            return UNKNOWN
        if isinstance(node,ast.Constant):
            return node.value
        if isinstance(node,ast.Name) and node.id in env:
            return resolve(env[node.id],env,depth+1)
        if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id == 'self' and node.attr in constants:
            return resolve(constants[node.attr],env,depth+1)
        if isinstance(node,(ast.List,ast.Tuple,ast.Set)):
            values = [resolve(item,env,depth+1) for item in node.elts]
            return values if all(item is not UNKNOWN for item in values) else UNKNOWN
        if isinstance(node,ast.Dict):
            keys = [resolve(item,env,depth+1) for item in node.keys]
            values = [resolve(item,env,depth+1) for item in node.values]
            if any(item is UNKNOWN for item in keys + values): return UNKNOWN
            try: return dict(zip(keys,values))
            except (TypeError,ValueError): return UNKNOWN
        if isinstance(node,ast.Subscript):
            value, key = resolve(node.value,env,depth+1), resolve(node.slice,env,depth+1)
            try: return value[key] if value is not UNKNOWN and key is not UNKNOWN else UNKNOWN
            except (KeyError,IndexError,TypeError): return UNKNOWN
        return UNKNOWN

    for node in constants.values():
        is_email = isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and imports.get(node.func.id) == 'EmailStep'
        email_tuple = isinstance(node,(ast.Tuple,ast.List)) and all(isinstance(item,ast.Name) and item.id in constants for item in node.elts)
        if resolve(node,constants) is UNKNOWN and not is_email and not email_tuple:
            fail(node,'Use statically resolvable class constants; arbitrary class initialization is unsupported.')
        if is_email:
            values = {item.arg:resolve(item.value,constants) for item in node.keywords}
            if node.args or set(values) != {'step_id','account','to','subject','body'} or any(not isinstance(value,str) for value in values.values()):
                fail(node,'EmailStep requires fixed string keyword arguments.')
            else:
                try:
                    keys = set().union(*(referenced_fields(values[key]) for key in ['to','subject','body']))
                    if not keys <= {item['key'] for item in specification['project_context']['input_definitions']}:
                        fail(node,'Email template references an unknown input.')
                except ValueError:
                    fail(node,'Email template must use simple input substitution.')
    expected = {'setup':['self','ctx'],'process':['self','ctx','inputs'],'teardown':['self','ctx'],'recover':['self','ctx','outcome']}
    for required in ['setup','process']:
        if required not in methods:
            fail(cls,f'Define the {required} lifecycle method.')
    for name,node in methods.items():
        args = node.args
        if name in {'execute','__init__'} or name.startswith('__'):
            fail(node,'Do not override framework lifecycle/resource ownership.')
        if args.vararg or args.kwarg or args.posonlyargs or args.kwonlyargs or args.defaults or node.decorator_list or node.returns or any(arg.annotation for arg in args.args):
            fail(node,'Use ordinary synchronous methods without decorators, annotations, defaults or variadic arguments.')
        if name in expected and [arg.arg for arg in args.args] != expected[name]:
            fail(node,'Lifecycle signature does not match the framework contract.')
        if name not in expected and (not name.startswith('_') or not args.args or args.args[0].arg != 'self'):
            fail(node,'Extra helpers must be private instance methods.')

    context = specification['project_context']
    elements = {item['id'] for item in context['captured_elements']}
    applications = {str(item['id']) for item in context['applications']}
    inputs = {item['key'] for item in context['input_definitions']}
    calls, helper_edges, visible = [], {}, set()
    def input_refs(node, env, seen=None):
        seen = set() if seen is None else seen
        result = set()
        for child in ast.walk(node):
            if isinstance(child,ast.Name) and child.id in env and child.id not in seen and len(seen)<50:
                seen.add(child.id)
                result.update(input_refs(env[child.id],env,seen))
            if isinstance(child,ast.Subscript) and isinstance(child.value,ast.Name) and child.value.id == 'inputs':
                key = resolve(child.slice,env)
                if not isinstance(key,str) or key not in inputs:
                    fail(child,'Input reference is unknown or dynamic; use a confirmed input key.')
                else: result.add(key)
            if isinstance(child,ast.Call) and isinstance(child.func,ast.Attribute) and isinstance(child.func.value,ast.Name) and child.func.value.id == 'inputs' and child.func.attr == 'get':
                key = resolve(child.args[0],env) if child.args else UNKNOWN
                if not isinstance(key,str) or key not in inputs:
                    fail(child,'Input lookup is unknown or dynamic.')
                else: result.add(key)
        return result

    for name,method in methods.items():
        env = dict(constants)
        for node in ast.walk(method):
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                env[node.targets[0].id] = node.value
        input_refs(method,env)
        helper_edges[name] = set()
        for node in ast.walk(method):
            if isinstance(node,(ast.Import,ast.ImportFrom,ast.AsyncFunctionDef,ast.Await,ast.Lambda,ast.Global,ast.Nonlocal,ast.While,ast.Yield,ast.YieldFrom,ast.ClassDef)):
                fail(node,'Dynamic imports, async, while/retry loops and nested execution constructs are unsupported.')
            if isinstance(node,ast.FunctionDef) and node is not method:
                fail(node,'Nested function definitions are unsupported.')
            if isinstance(node,ast.Attribute):
                if node.attr.startswith('__'):
                    fail(node,'Dunder introspection is unsupported.')
                value = node
                path = []
                while isinstance(value,ast.Attribute):
                    path.insert(0,value.attr); value = value.value
                if isinstance(value,ast.Name) and value.id == 'ctx' and path[0] not in ACTIONS | {'secrets','email'}:
                    fail(node,'Use public context actions, not browser/resources/internal state.')
                if isinstance(value,ast.Name) and value.id == 'ctx' and len(path)>1 and path not in [['secrets','get'],['email','send'],['email','send_step']]:
                    fail(node,'Do not inspect context adapter internals.')
            if not isinstance(node,ast.Call): continue
            function = node.func
            if isinstance(function,ast.Name):
                if function.id not in BUILTINS and imports.get(function.id) not in {'BusinessRejection','ExecutionCancelled','TechnicalError','EmailStep'}:
                    fail(node,'Call is outside the supported framework/builtin surface.')
            elif isinstance(function,ast.Attribute):
                if isinstance(function.value,ast.Name) and function.value.id == 'ctx':
                    action = function.attr
                    if action not in ACTIONS: fail(node,'Unknown context action.')
                    parameters = {'fill':['element_id','value'],'select_option':['element_id','value'],
                        'click':['element_id'],'read_text':['element_id'],'assert_visible':['element_id'],
                        'navigate':['application_id'],'step':['step_id'],'checkpoint':[],'business_completed':[]}.get(action,[])
                    supplied = parameters[:len(node.args)] + [item.arg for item in node.keywords]
                    if len(node.args)>len(parameters) or any(key not in parameters for key in supplied) or len(set(supplied)) != len(supplied) or set(supplied) != set(parameters):
                        fail(node,'Context action arguments do not match the framework API.')
                    argument = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg in {'element_id','application_id','step_id'}),None)
                    target = resolve(argument,env) if argument is not None else UNKNOWN
                    if action in {'fill','click','select_option','read_text','assert_visible'}:
                        if not isinstance(target,str) or target not in elements:
                            fail(node,'Element reference is unknown or dynamic; use a confirmed captured ID.')
                        calls.append((name,action,target,input_refs(node,env)))
                        if action == 'assert_visible': visible.add(name)
                    elif action == 'navigate' and str(target) not in applications:
                        fail(node,'Application reference is unknown or dynamic.')
                    elif action == 'step' and (not isinstance(target,str) or not target or len(target)>200):
                        fail(node,'Progress step names must be fixed nonempty strings.')
                elif isinstance(function.value,ast.Attribute) and isinstance(function.value.value,ast.Name) and function.value.value.id == 'ctx':
                    if (function.value.attr,function.attr) not in {('secrets','get'),('email','send'),('email','send_step')}:
                        fail(node,'Unknown secret/email context operation.')
                    elif function.value.attr == 'secrets':
                        key = resolve(node.args[0],env) if len(node.args)==1 and not node.keywords else UNKNOWN
                        if not isinstance(key,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*',key):
                            fail(node,'Use a fixed valid secret reference, never an actual secret value.')
                elif isinstance(function.value,ast.Name) and function.value.id == 'self' and function.attr in methods:
                    helper_edges[name].add(function.attr)
                elif function.attr not in STRING_METHODS:
                    fail(node,'Unknown method call; use supported context actions.')
            else:
                fail(node,'Dynamic callable expressions are unsupported.')
        for loop in (item for item in ast.walk(method) if isinstance(item,ast.For)):
            if any(isinstance(item,ast.Call) and isinstance(item.func,ast.Attribute) and item.func.attr in {'click','fill','select_option'} for item in ast.walk(loop)):
                fail(loop,'Do not put UI submissions/actions in loops; the framework owns row iteration.')

    def reachable(start):
        found, stack = set(), [start]
        while stack:
            item = stack.pop()
            if item in found: continue
            found.add(item); stack.extend(helper_edges.get(item,set()))
        return found
    decisions = specification['decisions']
    for owner, action, target, refs in calls:
        if owner in reachable('setup') and refs:
            fail(methods[owner],'Setup cannot use per-row inputs.')
        if action in {'fill','click','select_option'}:
            configured = [step for step in context['steps'] if target in step['element_ids']
                and {'fill':'fill','click':'click','select':'select_option'}.get(step['action']) == action]
            if not configured:
                fail(methods[owner],'UI mutation must match a configured step action and target.')
            elif owner in reachable('setup') and not any(step['id'] in decisions['setup_step_ids'] for step in configured):
                fail(methods[owner],'Per-row UI mutations cannot run during setup.')
            elif owner in reachable('process') and not any(step['id'] in decisions['per_row_step_ids'] for step in configured):
                fail(methods[owner],'Setup UI mutations cannot run for every row.')
    if not any(isinstance(item,ast.With) and any(isinstance(part.context_expr,ast.Call)
            and isinstance(part.context_expr.func,ast.Attribute) and isinstance(part.context_expr.func.value,ast.Name)
            and part.context_expr.func.value.id == 'ctx' and part.context_expr.func.attr == 'step'
            for part in item.items) for owner in reachable('process') if owner in methods for item in ast.walk(methods[owner])):
        fail(cls,'process must report progress through named ctx.step blocks.')
    for step in context['steps']:
        action = {'fill':'fill','click':'click','select':'select_option'}.get(step['action'])
        phase = 'setup' if step['id'] in decisions['setup_step_ids'] else 'process'
        matches = [(owner,kind,target,refs) for owner,kind,target,refs in calls if owner in reachable(phase) and kind == action and target in step['element_ids']]
        if not matches:
            fail(cls,f'Configured step {step["id"]} is not represented in its confirmed lifecycle phase.')
        elif action in {'fill','select_option'} and (not step['input_mapping'] or step['input_mapping']['key'] not in set().union(*(refs for _,_,_,refs in matches))):
            fail(cls,f'Configured step {step["id"]} does not use its mapped input field.')
    if not visible & reachable('process'):
        fail(cls,'process must include an explicit visible success assertion.')
    if not decisions['stop_on_nok'] or not decisions['stop_on_error']:
        recovery = methods.get('recover')
        if recovery is None or not visible & reachable('recover') or not any(isinstance(item,ast.Return) and isinstance(item.value,ast.Constant) and item.value.value is True for item in ast.walk(recovery)):
            fail(cls,'Continuation requires recover with an explicit state assertion and return True.')
    return list(dict.fromkeys(errors))[:20]
