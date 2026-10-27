from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def home(request):
    return render(request, "projects/home.html")


@require_GET
def status(request):
    return render(request, "projects/_status.html")
