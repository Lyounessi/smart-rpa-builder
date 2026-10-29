from django.contrib import admin
from projects.admin import ReadOnlyAdmin
from .models import ContextSnapshot, MuseBudget, MuseRequest


@admin.register(ContextSnapshot)
class SnapshotAdmin(ReadOnlyAdmin):
    list_display = ('id', 'project', 'contract_version', 'specification_hash', 'created_at')


@admin.register(MuseRequest)
class RequestAdmin(ReadOnlyAdmin):
    list_display = ('id', 'operation', 'model', 'outcome', 'accounted_usd', 'usage_known', 'created_at')


@admin.register(MuseBudget)
class BudgetAdmin(ReadOnlyAdmin):
    list_display = ('id', 'committed_usd')
