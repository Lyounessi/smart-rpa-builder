from django.contrib import admin
from django.urls import include, path

from projects import views
from projects import input_views
from execution import robot_views
from muse_builder import views as muse_views
from muse_builder import build_views

urlpatterns = [
    path('projects/<int:project_id>/datasets/new/', input_views.dataset_create, name='dataset-create'),
    path('projects/<int:project_id>/datasets/<int:dataset_id>/rows/new/', input_views.dataset_row_edit, name='dataset-row-create'),
    path('projects/<int:project_id>/datasets/<int:dataset_id>/rows/<int:row_id>/edit/', input_views.dataset_row_edit, name='dataset-row-edit'),
    path('projects/<int:project_id>/datasets/<int:dataset_id>/rows/<int:row_id>/duplicate/', input_views.dataset_row_edit, {'duplicate':True}, name='dataset-row-duplicate'),
    path('robots/<int:robot_id>/builds/<int:version>/test/', robot_views.test_build, name='robot-build-test'),
    path('projects/<int:project_id>/build/<uuid:session_id>/generate/', build_views.generate, name='muse-generate'),
    path('projects/<int:project_id>/build/', build_views.detail, name='muse-build'),
    path('projects/<int:project_id>/build/start/', build_views.start, name='muse-build-start'),
    path('projects/<int:project_id>/build/<uuid:session_id>/reply/', build_views.reply, name='muse-build-reply'),
    path('projects/<int:project_id>/build/<uuid:session_id>/messages/<int:message_id>/review/', build_views.proposals, name='muse-proposal-review'),
    path('projects/<int:project_id>/build/<uuid:session_id>/specification/', build_views.specification, name='muse-specification-edit'),
    path('projects/<int:project_id>/build/<uuid:session_id>/confirm/', build_views.confirm, name='muse-specification-confirm'),
    path('muse/usage/', muse_views.usage, name='muse-usage'),
    path('robots/', robot_views.robot_list, name='robot-list'),
    path('robots/<int:robot_id>/', robot_views.robot_detail, name='robot-detail'),
    path('robots/<int:robot_id>/builds/<int:version>/', robot_views.build_detail, name='robot-build-detail'),
    path('execution/', include('execution.urls')),
    path('projects/<int:project_id>/inputs/new/', input_views.input_edit, name='input-create'),
    path('projects/<int:project_id>/inputs/<int:input_id>/edit/', input_views.input_edit, name='input-edit'),
    path('projects/<int:project_id>/datasets/upload/', input_views.dataset_upload, name='dataset-upload'),
    path('projects/<int:project_id>/datasets/<int:dataset_id>/', input_views.dataset_detail, name='dataset-detail'),
    path('projects/<int:project_id>/datasets/<int:dataset_id>/confirm/', input_views.dataset_confirm, name='dataset-confirm'),
    path("inspector/", include("inspector.urls")),
    path("", views.home, name="home"),
    path("status/", views.status, name="status"),
    path("projects/new/", views.project_edit, name="project-create"),
    path("projects/<int:project_id>/", views.project_detail, name="project-detail"),
    path("projects/<int:project_id>/edit/", views.project_edit, name="project-edit"),
    path('projects/<int:project_id>/brief/', views.automation_brief_edit, name='project-brief-edit'),
    path("projects/<int:project_id>/applications/new/", views.window_edit, name="window-create"),
    path("projects/<int:project_id>/applications/<int:window_id>/edit/", views.window_edit, name="window-edit"),
    path("projects/<int:project_id>/steps/new/", views.step_edit, name="step-create"),
    path("projects/<int:project_id>/steps/target-options/", views.step_target_options, name="step-target-options"),
    path("projects/<int:project_id>/steps/<int:step_id>/edit/", views.step_edit, name="step-edit"),
    path("projects/<int:project_id>/steps/<int:step_id>/move/", views.step_move, name="step-move"),
    path("admin/", admin.site.urls),
]
