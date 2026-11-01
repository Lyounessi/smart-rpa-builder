"""Local workflow readiness and readable plan cards; no provider calls."""
from django.core.exceptions import ValidationError
from django.urls import reverse


def workflow_requirements(project):
    issues=[]
    steps=list(project.steps.select_related('window','input_column').prefetch_related('element_references__element'))
    if not steps:
        issues.append({'text':'Add at least one workflow step.','url':reverse('step-create',args=[project.pk])})
    for step in steps:
        missing=[]
        references=list(step.element_references.all())
        if step.action not in {'fill','click','select','read_text'}:
            missing.append('choose a supported action')
        if not step.window_id:
            missing.append('choose a target application')
        if not references:
            missing.append('capture a target element')
        if step.action in {'fill','select'} and not step.input_column_id:
            missing.append('map an existing input field')
        if step.action=='read_text' and not step.output_key:
            missing.append('name the output to save')
        try:
            step.clean()
            for reference in references:
                reference.clean()
        except ValidationError:
            missing.append('correct the target or input mapping')
        if missing:
            issues.append({'text':f'{step.position}. {step.name}: '+ '; '.join(dict.fromkeys(missing))+'.',
                'step_id':step.pk,'url':reverse('step-edit',args=[project.pk,step.pk])})
    return issues


def plan_cards(project,session=None,form=None):
    if session:
        steps=session.snapshot.project_data['steps']
        elements={e['id']:e['name'] for e in session.snapshot.project_data['captured_elements']}
    else:
        steps=[]
        elements={}
        for step in project.steps.select_related('input_column').prefetch_related('element_references__element'):
            refs=list(step.element_references.all())
            elements.update({str(ref.element_id):ref.element.name for ref in refs})
            steps.append({'id':step.pk,'position':step.position,'name':step.name,'action':step.action,
                'input_mapping':{'key':step.input_column.key} if step.input_column_id else None,
                'element_ids':[str(ref.element_id) for ref in refs],'output_key':step.output_key,
                'instruction':step.instruction})
    cards=[]
    for step in steps:
        targets=', '.join(elements.get(pk,'Captured target') for pk in step['element_ids']) or 'Target missing'
        key=(step.get('input_mapping') or {}).get('key')
        action=step['action']
        summary={'fill':f'Fill {targets} using {key or "an input field (missing)"}',
            'select':f'Select an option in {targets} using {key or "an input field (missing)"}',
            'click':f'Click {targets} · no input value required',
            'read_text':f'Read {targets} → save as {step.get("output_key") or "output (missing)"}'}.get(action,'Choose a supported action')
        field=form[f'phase_{step["id"]}'] if form and f'phase_{step["id"]}' in form.fields else None
        cards.append({**step,'summary':summary,'phase_field':field,
            'edit_url':reverse('step-edit',args=[project.pk,step['id']])})
    return cards
