from django.contrib import admin
from projects.admin import ReadOnlyAdmin
from .models import ActionRecord, Robot, RobotBuild, RobotRun, RowAttempt, ProgressEvent


@admin.register(Robot)
class RobotAdmin(ReadOnlyAdmin):
    list_display = ('name', 'project', 'created_at')


@admin.register(RobotBuild)
class BuildAdmin(ReadOnlyAdmin):
    list_display = ('robot', 'version', 'origin', 'status', 'is_draft', 'created_at')


@admin.register(RobotRun)
class RunAdmin(ReadOnlyAdmin):
    list_display = ('id', 'robot_name', 'build', 'state', 'dataset', 'started_at', 'finished_at')
    list_filter = ('state',)


@admin.register(RowAttempt)
class AttemptAdmin(ReadOnlyAdmin):
    list_display = ('run', 'row', 'outcome', 'business_completed_at', 'failed_step')


@admin.register(ActionRecord)
class ActionAdmin(ReadOnlyAdmin):
    list_display = ('attempt', 'step_id', 'action_type', 'status', 'updated_at')


@admin.register(ProgressEvent)
class EventAdmin(ReadOnlyAdmin):
    list_display = ('run', 'kind', 'row_reference', 'step', 'created_at')
