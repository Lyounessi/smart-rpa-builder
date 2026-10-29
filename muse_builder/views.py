from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_GET
from .models import MuseBudget, MuseRequest


@require_GET
def usage(request):
    budget = MuseBudget.objects.filter(pk=1).first()
    return render(request, 'muse_builder/usage.html', {'budget':budget, 'limit':settings.MUSE_BUDGET_USD,
        'page':Paginator(MuseRequest.objects.select_related('snapshot__project'), 25).get_page(request.GET.get('page'))})
