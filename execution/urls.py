from django.urls import path
from . import views

urlpatterns = [path('<uuid:run_id>/', views.detail, name='run-detail'),
               path('<uuid:run_id>/cancel/', views.cancel, name='run-cancel')]
