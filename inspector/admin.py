from django.contrib import admin

from projects.admin import ReadOnlyAdmin
from .models import ApplicationWindow, CapturedElement, CaptureDraft, InspectionCommand, InspectionSession


@admin.register(ApplicationWindow)
class ApplicationWindowAdmin(ReadOnlyAdmin):
    list_display = ('name', 'project', 'application_type', 'target_url')
    list_select_related = ('project',)
    search_fields = ('name', 'project__name', 'target_url')
    list_filter = ('application_type', 'project')


@admin.register(CapturedElement)
class CapturedElementAdmin(ReadOnlyAdmin):
    list_display = ('name', 'id', 'window', 'element_type', 'validated_at')
    list_select_related = ('window',)
    search_fields = ('name', 'id', 'window__name', 'window__project__name')
    list_filter = ('window__project', 'element_type')


@admin.register(CaptureDraft)
class CaptureDraftAdmin(ReadOnlyAdmin):
    list_display = ('id', 'step', 'status', 'created_at')
    list_select_related = ('step',)
    list_filter = ('status',)


@admin.register(InspectionSession)
class InspectionSessionAdmin(ReadOnlyAdmin):
    list_display = ('id', 'project', 'step', 'status', 'heartbeat')
    list_select_related = ('project', 'step')
    list_filter = ('status', 'project')


@admin.register(InspectionCommand)
class InspectionCommandAdmin(ReadOnlyAdmin):
    list_display = ('id', 'session', 'operation', 'status', 'created_at')
    list_select_related = ('session',)
    list_filter = ('operation', 'status')
