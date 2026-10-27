from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import ProjectForm, StepForm, WindowForm
from .models import Project
from .services import move_step, save_new_step


@require_GET
def home(request):
    return render(request, "projects/home.html", {"projects": Project.objects.order_by("-updated_at")})


@require_GET
def status(request):
    return render(request, "projects/_status.html")


def successful_save(request, project):
    url = reverse("project-detail", args=[project.pk])
    if request.headers.get("HX-Request") == "true":
        response = render(request, "projects/_saved.html")
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def form_response(request, form, title, project=None):
    template = "projects/_form.html" if request.headers.get("HX-Request") == "true" else "projects/form.html"
    return render(request, template, {"form": form, "title": title, "project": project})


@require_http_methods(["GET", "POST"])
def project_edit(request, project_id=None):
    project = get_object_or_404(Project, pk=project_id) if project_id else None
    form = ProjectForm(request.POST if request.method == "POST" else None, instance=project)
    if request.method == "POST" and form.is_valid():
        return successful_save(request, form.save())
    return form_response(request, form, "Edit project" if project else "Create project", project)


@require_GET
def project_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    steps = project.steps.select_related("window").prefetch_related("element_references__element")
    return render(request, "projects/detail.html", {"project": project, "steps": steps})


@require_http_methods(["GET", "POST"])
def window_edit(request, project_id, window_id=None):
    project = get_object_or_404(Project, pk=project_id)
    window = get_object_or_404(project.windows, pk=window_id, application_type="web") if window_id else None
    form = WindowForm(request.POST if request.method == "POST" else None, instance=window)
    form.instance.project = project
    if request.method == "POST" and form.is_valid():
        form.save()
        return successful_save(request, project)
    return form_response(request, form, "Edit target application" if window else "Add target application", project)


@require_http_methods(["GET", "POST"])
def step_edit(request, project_id, step_id=None):
    project = get_object_or_404(Project, pk=project_id)
    step = get_object_or_404(project.steps, pk=step_id) if step_id else None
    form = StepForm(request.POST if request.method == "POST" else None, instance=step, project=project)
    if request.method == "POST" and form.is_valid():
        form.save() if step else save_new_step(form, project)
        return successful_save(request, project)
    return form_response(request, form, "Edit step" if step else "Add workflow step", project)


@require_GET
def step_target_options(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    form = StepForm(request.GET, project=project)
    return render(request, "projects/_target_options.html", {"elements": form.fields["target"].queryset})


@require_POST
def step_move(request, project_id, step_id):
    project = get_object_or_404(Project, pk=project_id)
    step = get_object_or_404(project.steps, pk=step_id)
    direction = request.POST.get("direction")
    if direction not in {"up", "down"}:
        return HttpResponseBadRequest("Choose up or down.")
    move_step(step, direction)
    if request.headers.get("HX-Request") == "true":
        return render(request, "projects/_steps.html", {"project": project, "steps": project.steps.select_related("window").prefetch_related("element_references__element")})
    return successful_save(request, project)
