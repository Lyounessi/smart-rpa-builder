from django.contrib import admin
from django.urls import path

from projects import views

urlpatterns = [
    path("", views.home, name="home"),
    path("status/", views.status, name="status"),
    path("projects/new/", views.project_edit, name="project-create"),
    path("projects/<int:project_id>/", views.project_detail, name="project-detail"),
    path("projects/<int:project_id>/edit/", views.project_edit, name="project-edit"),
    path("projects/<int:project_id>/applications/new/", views.window_edit, name="window-create"),
    path("projects/<int:project_id>/applications/<int:window_id>/edit/", views.window_edit, name="window-edit"),
    path("projects/<int:project_id>/steps/new/", views.step_edit, name="step-create"),
    path("projects/<int:project_id>/steps/<int:step_id>/edit/", views.step_edit, name="step-edit"),
    path("projects/<int:project_id>/steps/<int:step_id>/move/", views.step_move, name="step-move"),
    path("admin/", admin.site.urls),
]
