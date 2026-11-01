from django import forms
from django.utils.html import format_html


class ReplyForm(forms.Form):
    message = forms.CharField(required=False, max_length=2000, label='Additional workflow context', widget=forms.Textarea(attrs={'rows':3}))
    include_images = forms.BooleanField(required=False, label='Include saved screenshots again (more input tokens)')

    def __init__(self, *args, session, **kwargs):
        super().__init__(*args, **kwargs)
        for question in session.questions.filter(resolved=False).order_by('pk'):
            self.fields[f'question_{question.pk}'] = forms.CharField(required=False, max_length=2000,
                label=question.text, initial=question.answer,
                help_text=format_html('Suggested answers: {}', ' / '.join(question.choices)) if question.choices else '',
                widget=forms.Textarea(attrs={'rows':2}))
        self.order_fields([key for key in self.fields if key.startswith('question_')] + ['message','include_images'])


class StepChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, step):
        return f'{step.position}. {step.name}'


class SpecificationForm(forms.Form):
    setup_step_ids = StepChoices(queryset=None, required=False, label='Setup steps (run once)')
    per_row_step_ids = StepChoices(queryset=None, label='Steps repeated for every row')
    finalization_step_ids = StepChoices(queryset=None, required=False, label='Final checks (once after all selected rows succeed)')
    stop_on_nok = forms.TypedChoiceField(choices=[('true','Stop'), ('false','Continue after recovery')], coerce=lambda v:v == 'true', label='Known business rejection policy')
    stop_on_error = forms.TypedChoiceField(choices=[('true','Stop'), ('false','Continue after recovery')], coerce=lambda v:v == 'true', label='Technical error policy')
    success_criteria = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={'rows':3}))
    rejection_handling = forms.CharField(max_length=1000, label='Known rejection handling', help_text='Describe known rejections, or explicitly state none are known.', widget=forms.Textarea(attrs={'rows':2}))
    recovery_plan = forms.CharField(required=False, max_length=1000, help_text='Required when either policy allows continuation. Explain how the robot restores a known application state.', widget=forms.Textarea(attrs={'rows':2}))
    resolve_questions = forms.BooleanField(required=False, label='I have explicitly resolved the outstanding questions in these decisions')
    unsupported_request_resolution = forms.CharField(required=False, max_length=1000,
        label='Resolution of Muse capability warnings',
        help_text='If Muse flagged unsupported requests, explain how you removed or replaced them with supported actions. This does not enable unsupported capabilities.',
        widget=forms.Textarea(attrs={'rows':2}))

    def __init__(self, *args, project, guided=False, **kwargs):
        steps=list(project.steps.all())
        self.guided=guided
        if guided:
            data=args[0] if args else kwargs.get('data')
            if data is not None:
                data=data.copy()
                allocation={'setup':[],'per_row':[],'finalization':[]}
                for step in steps:
                    phase=data.get(f'phase_{step.pk}')
                    if phase in allocation:
                        allocation[phase].append(str(step.pk))
                for phase,ids in allocation.items():
                    if hasattr(data,'setlist'):
                        data.setlist(phase+'_step_ids',ids)
                    else:
                        data[phase+'_step_ids']=ids
                if args:
                    args=(data,*args[1:])
                else:
                    kwargs['data']=data
        super().__init__(*args, **kwargs)
        for name in ['setup_step_ids','per_row_step_ids','finalization_step_ids']:
            self.fields[name].queryset = project.steps.all()
        self.step_ids = set(project.steps.values_list('pk', flat=True))
        self.read_step_ids = set(project.steps.filter(action='read_text').values_list('pk', flat=True))
        self.input_step_ids = set(project.steps.filter(action__in=['fill','select']).values_list('pk', flat=True))
        if guided:
            labels={'setup':'Before processing · once','per_row':'For each record','finalization':'After processing · final check'}
            for step in steps:
                phases=['per_row'] if step.action in {'fill','select'} else (['per_row','finalization'] if step.action=='read_text' else list(labels))
                assigned=[phase for phase in labels if step.pk in self.initial.get(phase+'_step_ids',[])]
                self.fields[f'phase_{step.pk}']=forms.ChoiceField(label=f'When to run {step.name}',
                    choices=[('','Choose when this step runs')]+[(phase,labels[phase]) for phase in phases],
                    initial=assigned[0] if len(assigned)==1 else '')
            self.fields['success_criteria'].help_text='Describe proof for each record and for the final result. Example: after Submit, the round advances OR the completion screen appears; after all records, save Congratulations.'

    def clean(self):
        data = super().clean()
        if all(key in data for key in ['setup_step_ids','per_row_step_ids','finalization_step_ids']):
            setup, rows = set(data['setup_step_ids'].values_list('pk',flat=True)), set(data['per_row_step_ids'].values_list('pk',flat=True))
            final = set(data['finalization_step_ids'].values_list('pk',flat=True))
            if setup & rows or setup & final or rows & final or setup | rows | final != self.step_ids:
                raise forms.ValidationError('Allocate each workflow step exactly once to setup, per-row processing, or final checks.')
            if setup & self.read_step_ids:
                self.add_error('setup_step_ids', 'Read text outputs belong to per-record processing or final checks, not setup.')
            if (setup | final) & self.input_step_ids:
                self.add_error('finalization_step_ids' if final & self.input_step_ids else 'setup_step_ids',
                    'Steps using mapped input values must run per row; setup and final checks have no current input.')
        if (data.get('stop_on_nok') is False or data.get('stop_on_error') is False) and not data.get('recovery_plan'):
            self.add_error('recovery_plan', 'Explain how to restore a known state before continuing.')
        return data

    def decisions(self):
        return {key:list(value.values_list('pk',flat=True)) if key.endswith('_step_ids') else value
                for key,value in self.cleaned_data.items() if key != 'resolve_questions' and not key.startswith('phase_')}


def decision_form_data(decisions):
    return {key:('true' if value else 'false') if isinstance(value,bool) else value for key,value in decisions.items()}
