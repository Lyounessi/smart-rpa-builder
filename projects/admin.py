from django.contrib import admin

from .models import Dataset, DatasetRow, Project, ProjectInput, StepElementReference, WorkflowStep


class ReadOnlyAdmin(admin.ModelAdmin):
    """Inspect records here; workflow edits go through the validated editor."""

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Project)
class ProjectAdmin(ReadOnlyAdmin):
    list_display = ('name', 'application_scope', 'updated_at')
    search_fields = ('name', 'description')
    list_filter = ('application_scope',)


@admin.register(WorkflowStep)
class WorkflowStepAdmin(ReadOnlyAdmin):
    list_display = ('name', 'project', 'position', 'window', 'action', 'input_column', 'updated_at')
    list_select_related = ('project', 'window', 'input_column')
    search_fields = ('name', 'instruction', 'project__name')
    list_filter = ('project',)


@admin.register(StepElementReference)
class StepElementReferenceAdmin(ReadOnlyAdmin):
    list_display = ('step', 'element', 'created_at')
    list_select_related = ('step', 'element')
    search_fields = ('step__name', 'element__name')


@admin.register(ProjectInput)
class ProjectInputAdmin(ReadOnlyAdmin):
    list_display = ('key', 'project', 'data_type', 'required')
    list_filter = ('project', 'data_type', 'required')
    search_fields = ('key', 'description', 'project__name')


@admin.register(Dataset)
class DatasetAdmin(ReadOnlyAdmin):
    list_display = ('name', 'project', 'status', 'row_count', 'invalid_row_count', 'created_at')
    list_filter = ('project', 'status')


@admin.register(DatasetRow)
class DatasetRowAdmin(ReadOnlyAdmin):
    list_display = ('dataset', 'row_number','processing_status','deleted_at')
    list_filter = ('dataset',)
