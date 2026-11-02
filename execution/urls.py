from django.urls import path
from . import views
from .recordings import recording

urlpatterns = [path('<uuid:run_id>/', views.detail, name='run-detail'),
               path('<uuid:run_id>/recordings/<int:index>/', recording, name='run-recording'),
               path('<uuid:run_id>/logs/', views.technical_logs, name='run-logs'),
               path('<uuid:run_id>/cancel/', views.cancel, name='run-cancel')]
