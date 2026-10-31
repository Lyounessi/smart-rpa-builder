"""Project results are execution attempts, never workflow actions or mutable input copies."""
from django import forms
from django.core.paginator import Paginator
from django.db.models import Case, When, DateTimeField, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from projects.models import Project
from .models import RobotRun, RobotBuild, RowAttempt
from .robot_views import duration, seconds
from .views import explain_attempts


class ResultRunChoice(forms.ModelChoiceField):
    def label_from_instance(self,run):
        stamp=timezone.localtime(run.started_at or run.created_at).strftime('%Y-%m-%d %H:%M')
        version=f'v{run.build.version}' if run.build_id else 'unrecorded version'
        return f'{stamp} · {run.dataset.name} · {version} · {run.state} · {str(run.pk)[:8]}'


class ResultFilterForm(forms.Form):
    status = forms.ChoiceField(required=False, choices=[('treated','Treated records'),
        ('unconfirmed','Unconfirmed / failed attempts'),('all','All attempts')])
    date_from = forms.DateField(required=False,label='From date',widget=forms.DateInput(attrs={'type':'date'}))
    date_to = forms.DateField(required=False,label='To date (inclusive)',widget=forms.DateInput(attrs={'type':'date'}))
    dataset = forms.ModelChoiceField(queryset=None,required=False,empty_label='All datasets')
    run = ResultRunChoice(queryset=None,required=False,empty_label='All runs')
    version = forms.ChoiceField(required=False,choices=[])

    def __init__(self,*args,project,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['dataset'].queryset=project.datasets.all()
        self.fields['run'].queryset=RobotRun.objects.filter(dataset__project=project).select_related('dataset','build').order_by('-created_at')
        versions=RobotBuild.objects.filter(robot__project=project).values_list('version',flat=True).distinct().order_by('-version')
        self.fields['version'].choices=[('','All versions')]+[(str(v),f'Version {v}') for v in versions]

    def clean(self):
        data=super().clean()
        if data.get('date_from') and data.get('date_to') and data['date_from']>data['date_to']:
            self.add_error('date_to','End date must be on or after the start date.')
        if data.get('run') and data.get('dataset') and data['run'].dataset_id!=data['dataset'].pk:
            self.add_error('run','Choose a run from the selected dataset.')
        return data


@require_GET
def project_results(request,project_id):
    project=get_object_or_404(Project,pk=project_id)
    form=ResultFilterForm(request.GET or {'status':'treated'},project=project)
    attempts=RowAttempt.objects.filter(run__dataset__project=project).select_related('run__dataset','run__build','row')
    treated=Q(business_completed_at__isnull=False)|Q(outcome='OK')
    attempts=attempts.annotate(treatment_at=Case(
        When(business_completed_at__isnull=False,then='business_completed_at'),
        When(outcome='OK',then='finished_at'),output_field=DateTimeField()))
    attempts=attempts.annotate(filter_at=Case(When(treated,then='treatment_at'),
        default=Coalesce('finished_at','started_at','created_at'),output_field=DateTimeField()))
    selected_status='treated'
    if form.is_valid():
        data=form.cleaned_data
        selected_status=data.get('status') or 'treated'
        if selected_status=='treated': attempts=attempts.filter(treated)
        elif selected_status=='unconfirmed': attempts=attempts.exclude(treated)
        for key,field in [('dataset','run__dataset'),('run','run'),('version','run__build__version')]:
            if data.get(key): attempts=attempts.filter(**{field:data[key]})
        if data.get('date_from'): attempts=attempts.filter(filter_at__date__gte=data['date_from'])
        if data.get('date_to'): attempts=attempts.filter(filter_at__date__lte=data['date_to'])
    else:
        attempts=attempts.none()
    page=Paginator(attempts.order_by('-filter_at','-pk'),25).get_page(request.GET.get('page'))
    records=list(page.object_list)
    explain_attempts(records)
    for attempt in records:
        attempt.elapsed=duration(seconds(attempt.started_at,attempt.finished_at))
        attempt.is_treated=attempt.business_completed_at is not None or attempt.outcome=='OK'
    page.object_list=records
    query=request.GET.copy()
    query.pop('page',None)
    return render(request,'execution/project_results.html',{'project':project,'form':form,'page':page,
        'filter_query':query.urlencode(),'selected_status':selected_status,'results_timezone':timezone.get_current_timezone_name()})
