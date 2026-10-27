from django import forms
from django.db import transaction

from inspector.models import ApplicationWindow, CapturedElement
from .models import Project, StepElementReference, WorkflowStep


class ApplicationScopeSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value == Project.ApplicationScope.DESKTOP:
            option["attrs"]["disabled"] = True
            option["label"] = "Desktop application — coming later"
        elif value == Project.ApplicationScope.MULTIPLE:
            option["label"] = "Multiple applications — web only for now"
        return option


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "application_scope", "description"]
        labels = {"application_scope": "Application setup"}
        widgets = {"application_scope": ApplicationScopeSelect}
        help_texts = {"application_scope": "The hackathon version supports web applications. Desktop and mixed web/desktop workflows are coming later."}

    def clean_application_scope(self):
        scope = self.cleaned_data["application_scope"]
        if scope == Project.ApplicationScope.DESKTOP:
            raise forms.ValidationError("Desktop projects are coming later. Choose web or multiple web applications.")
        return scope


class WindowForm(forms.ModelForm):
    class Meta:
        model = ApplicationWindow
        fields = ["name", "target_url"]

    target_url = forms.URLField(max_length=2048, label="Starting URL", help_text="Use an http:// or https:// address without credentials or tokens.")

    def clean_target_url(self):
        from urllib.parse import urlsplit
        value = self.cleaned_data["target_url"]
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise forms.ValidationError("Use an HTTP(S) URL without embedded credentials.")
        return value


class StepForm(forms.ModelForm):
    target = forms.ModelChoiceField(queryset=CapturedElement.objects.none(), required=False, help_text="Optional. Browser capture will be added in the next milestone.")

    class Meta:
        model = WorkflowStep
        fields = ["name", "instruction", "window"]
        labels = {"window": "Target application"}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.project = project
        self.fields["window"].queryset = project.windows.filter(application_type="web")
        self.fields["target"].queryset = CapturedElement.objects.filter(window__project=project)
        if self.instance.pk:
            reference = self.instance.element_references.first()
            self.initial["target"] = reference.element_id if reference else None

    def clean(self):
        data = super().clean()
        target, window = data.get("target"), data.get("window")
        if target and window and target.window_id != window.pk:
            self.add_error("target", "Choose an element from the selected application.")
        if target and not window:
            data["window"] = target.window
        return data

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("Steps and their references must be saved together.")
        step = super().save()
        step.element_references.all().delete()
        if self.cleaned_data.get("target"):
            StepElementReference.objects.create(step=step, element=self.cleaned_data["target"])
        return step
