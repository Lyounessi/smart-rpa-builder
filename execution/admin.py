from django.contrib import admin
from projects.admin import ReadOnlyAdmin
from .models import RobotRun, RowAttempt, ProgressEvent


@admin.register(RobotRun)
class RunAdmin(ReadOnlyAdmin):
    list_display = ('id', 'robot_name', 'state', 'dataset', 'created_at')
    list_filter = ('state',)


@admin.register(RowAttempt)
class AttemptAdmin(ReadOnlyAdmin):
    list_display = ('run', 'row', 'outcome', 'failed_step')


@admin.register(ProgressEvent)
class EventAdmin(ReadOnlyAdmin):
    list_display = ('run', 'kind', 'row_reference', 'step', 'created_at')
