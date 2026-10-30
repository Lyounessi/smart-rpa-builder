from django import forms
from django.db.models import Count, Q
from django.urls import reverse
from .limits import MAX_TEST_ROWS


class DraftTestForm(forms.Form):
    dataset = forms.ModelChoiceField(queryset=None)
    row_limit = forms.IntegerField(min_value=1,max_value=MAX_TEST_ROWS,initial=2,label='Maximum pending rows')
    record_screen = forms.BooleanField(required=False,label='Record browser page video')
    reviewed_digest = forms.CharField(widget=forms.HiddenInput)
    acknowledged = forms.BooleanField(label='I reviewed this source version and allow it to run locally, act on its target application and update the selected input rows.')

    def __init__(self,*args,build,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['dataset'].queryset = build.robot.project.datasets.filter(status='ready')
        self.initial['reviewed_digest'] = build.source_digest
        if build.confirmed_specification.get('decisions',{}).get('finalization_step_ids'):
            self.fields['row_limit'].help_text = 'This version has a final check after all selected rows succeed. Choose enough inputs to reach the application’s final state; a partial test may fail that final check.'


class VersionChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):
        return f'Version {obj.version} · {obj.get_origin_display()} · reviewed before each run'


class PendingDatasetChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):
        return f'{obj.name} · {obj.pending_count} pending inputs'


class RobotRunForm(DraftTestForm):
    build = VersionChoice(queryset=None,label='Robot version',empty_label=None)
    dataset = PendingDatasetChoice(queryset=None,label='Input dataset',empty_label=None)

    def __init__(self,*args,robot,selected_build=None,**kwargs):
        forms.Form.__init__(self,*args,**kwargs)
        self.fields['build'].queryset=robot.builds.filter(is_draft=True,status='validated',specification_snapshot__isnull=False)
        self.fields['dataset'].queryset=robot.project.datasets.filter(status='ready',invalid_row_count=0).annotate(
            pending_count=Count('rows',filter=Q(rows__processing_status='pending',rows__errors=[],rows__deleted_at__isnull=True))
        ).filter(pending_count__gt=0)
        self.initial['build']=selected_build.pk if selected_build else None
        self.initial['reviewed_digest']=selected_build.source_digest if selected_build else ''
        if selected_build and selected_build.confirmed_specification.get('decisions',{}).get('finalization_step_ids'):
            self.fields['row_limit'].help_text = 'Final verification runs after all selected rows succeed. For a full challenge, select all required rows; a partial test may not reach its final screen.'
        self.fields['acknowledged'].label='I reviewed this version’s code and allow it to run locally, act on the target application and update these inputs.'
        self.order_fields(['build','dataset','row_limit','record_screen','reviewed_digest','acknowledged'])
        for key in ['build','dataset']:
            self.fields[key].widget.attrs.update({'hx-get':reverse('robot-run',args=[robot.pk]),
                'hx-target':'#run-dialog-content','hx-include':'closest form','hx-trigger':'change',
                'hx-params':'build,dataset,row_limit,record_screen'})

    def clean(self):
        data=super().clean()
        build,dataset=data.get('build'),data.get('dataset')
        if build and dataset:
            from .draft_tests import input_schema_matches
            if not input_schema_matches(build,dataset):
                self.add_error('dataset','This dataset does not match the selected version’s input definitions. Create a current dataset.')
        return data
