from django.contrib import admin
from django.urls import path

from projects.views import home, status

urlpatterns = [path("", home, name="home"), path("status/", status, name="status"), path("admin/", admin.site.urls)]
