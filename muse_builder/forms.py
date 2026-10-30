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

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ['setup_step_ids','per_row_step_ids','finalization_step_ids']:
            self.fields[name].queryset = project.steps.all()
        self.step_ids = set(project.steps.values_list('pk', flat=True))
        self.read_step_ids = set(project.steps.filter(action='read_text').values_list('pk', flat=True))
        self.input_step_ids = set(project.steps.filter(action__in=['fill','select']).values_list('pk', flat=True))

    def clean(self):
        data = super().clean()
        if all(key in data for key in ['setup_step_ids','per_row_step_ids','finalization_step_ids']):
            setup, rows = set(data['setup_step_ids'].values_list('pk',flat=True)), set(data['per_row_step_ids'].values_list('pk',flat=True))
            final = set(data['finalization_step_ids'].values_list('pk',flat=True))
            if setup & rows or setup & final or rows & final or setup | rows | final != self.step_ids:
                raise forms.ValidationError('Allocate each workflow step exactly once to setup, per-row processing, or final checks.')
            if setup & self.read_step_ids:
                self.add_error('setup_step_ids', 'Read text outputs must run for each input row, not during setup.')
            if (setup | final) & self.input_step_ids:
                self.add_error('finalization_step_ids' if final & self.input_step_ids else 'setup_step_ids',
                    'Steps using mapped input values must run per row; setup and final checks have no current input.')
        if (data.get('stop_on_nok') is False or data.get('stop_on_error') is False) and not data.get('recovery_plan'):
            self.add_error('recovery_plan', 'Explain how to restore a known state before continuing.')
        return data

    def decisions(self):
        return {key:list(value.values_list('pk',flat=True)) if key.endswith('_step_ids') else value
                for key,value in self.cleaned_data.items() if key != 'resolve_questions'}


def decision_form_data(decisions):
    return {key:('true' if value else 'false') if isinstance(value,bool) else value for key,value in decisions.items()}
