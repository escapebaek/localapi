from django.urls import path, re_path

from . import views

app_name = "localai"

urlpatterns = [
    path("jobs/", views.submit_job, name="submit"),
    re_path(r"^jobs/(?P<job_id>[0-9a-f]{32})/$", views.job_status, name="status"),
]
