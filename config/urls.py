from django.contrib import admin
from django.urls import include, path

from projects import views
from projects import input_views
from execution import robot_views

urlpatterns = [
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
