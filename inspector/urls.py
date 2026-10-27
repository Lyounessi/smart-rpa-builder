from django.urls import path
from . import views

urlpatterns = [
    path('health/<uuid:session_id>/', views.health, name='inspector-health'),
    path('<int:project_id>/steps/<int:step_id>/', views.step_inspector, name='step-inspector'),
    path('<int:project_id>/steps/<int:step_id>/launch/', views.launch, name='inspector-launch'),
    path('<int:project_id>/steps/<int:step_id>/sessions/<uuid:session_id>/command/', views.command, name='inspector-command'),
    path('<int:project_id>/steps/<int:step_id>/drafts/<uuid:draft_id>/review/', views.review, name='inspector-review'),
    path('<int:project_id>/steps/<int:step_id>/images/<str:source>/<uuid:capture_id>/<str:kind>/', views.screenshot, name='inspector-screenshot'),
]
