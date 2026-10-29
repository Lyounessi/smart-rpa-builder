from django.contrib import admin
from projects.admin import ReadOnlyAdmin
from .models import (BuildMessage, BuildOperation, BuildProposal, BuildQuestion, BuildSession,
                     ContextSnapshot, GenerationJob, MuseBudget, MuseRequest)


@admin.register(ContextSnapshot)
class SnapshotAdmin(ReadOnlyAdmin):
    list_display = ('id', 'project', 'contract_version', 'specification_hash', 'created_at')


@admin.register(MuseRequest)
class RequestAdmin(ReadOnlyAdmin):
    list_display = ('id', 'operation', 'model', 'outcome', 'accounted_usd', 'usage_known', 'created_at')


@admin.register(MuseBudget)
class BudgetAdmin(ReadOnlyAdmin):
    list_display = ('id', 'committed_usd')


@admin.register(BuildSession)
class SessionAdmin(ReadOnlyAdmin):
    list_display = ('id','project','state','rounds_used','confirmed_at')


@admin.register(BuildMessage)
class MessageAdmin(ReadOnlyAdmin):
    list_display = ('session','role','created_at','review_status')


@admin.register(BuildQuestion)
class QuestionAdmin(ReadOnlyAdmin):
    list_display = ('session','key','resolved')


@admin.register(BuildProposal)
class ProposalAdmin(ReadOnlyAdmin):
    list_display = ('session','field','step_id','status')


@admin.register(BuildOperation)
class OperationAdmin(ReadOnlyAdmin):
    list_display = ('id','session','kind','round_number','status','heartbeat')


@admin.register(GenerationJob)
class GenerationAdmin(ReadOnlyAdmin):
    list_display = ('id','session','robot_name','state','result_build','created_at')
