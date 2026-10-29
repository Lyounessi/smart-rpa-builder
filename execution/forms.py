from django import forms


class DraftTestForm(forms.Form):
    dataset = forms.ModelChoiceField(queryset=None)
    row_limit = forms.IntegerField(min_value=1,max_value=5,initial=2,label='Maximum pending rows')
    record_screen = forms.BooleanField(required=False,label='Record browser page video')
    reviewed_digest = forms.CharField(widget=forms.HiddenInput)
    acknowledged = forms.BooleanField(label='I reviewed this source version and allow it to run locally, act on its target application and update the selected input rows.')

    def __init__(self,*args,build,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['dataset'].queryset = build.robot.project.datasets.filter(status='ready')
        self.initial['reviewed_digest'] = build.source_digest
