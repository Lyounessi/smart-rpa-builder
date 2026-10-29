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
    stop_on_nok = forms.TypedChoiceField(choices=[('true','Stop'), ('false','Continue after recovery')], coerce=lambda v:v == 'true', label='Known business rejection policy')
    stop_on_error = forms.TypedChoiceField(choices=[('true','Stop'), ('false','Continue after recovery')], coerce=lambda v:v == 'true', label='Technical error policy')
    success_criteria = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={'rows':3}))
    rejection_handling = forms.CharField(max_length=1000, label='Known rejection handling', help_text='Describe known rejections, or explicitly state none are known.', widget=forms.Textarea(attrs={'rows':2}))
    recovery_plan = forms.CharField(required=False, max_length=1000, help_text='Required when either policy allows continuation. Explain how the robot restores a known application state.', widget=forms.Textarea(attrs={'rows':2}))
    resolve_questions = forms.BooleanField(required=False, label='I have explicitly resolved the outstanding questions in these decisions')

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ['setup_step_ids','per_row_step_ids']:
            self.fields[name].queryset = project.steps.all()
        self.step_ids = set(project.steps.values_list('pk', flat=True))

    def clean(self):
        data = super().clean()
        if 'setup_step_ids' in data and 'per_row_step_ids' in data:
            setup, rows = set(data['setup_step_ids'].values_list('pk',flat=True)), set(data['per_row_step_ids'].values_list('pk',flat=True))
            if setup & rows or setup | rows != self.step_ids:
                raise forms.ValidationError('Allocate each workflow step exactly once to setup or per-row processing.')
        if (data.get('stop_on_nok') is False or data.get('stop_on_error') is False) and not data.get('recovery_plan'):
            self.add_error('recovery_plan', 'Explain how to restore a known state before continuing.')
        return data

    def decisions(self):
        return {key:list(value.values_list('pk',flat=True)) if key.endswith('_step_ids') else value
                for key,value in self.cleaned_data.items() if key != 'resolve_questions'}


def decision_form_data(decisions):
    return {key:('true' if value else 'false') if isinstance(value,bool) else value for key,value in decisions.items()}
