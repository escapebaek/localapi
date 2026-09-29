"""Tests for examples/django/localai against a fake gateway."""

import json
import sys
from pathlib import Path

import pytest

django = pytest.importorskip("django")
pytest.importorskip("requests")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples" / "django"))

from django.conf import settings  # noqa: E402

if not settings.configured:
    settings.configure(
        SECRET_KEY="test",
        ALLOWED_HOSTS=["testserver"],
        INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions"],
        MIDDLEWARE=[
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
        ],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        ROOT_URLCONF=__name__,
        SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
        LOCALAI_URL="https://laptop.example.ts.net",
        LOCALAI_API_KEY="k",
    )
    django.setup()

from django.urls import include, path  # noqa: E402

urlpatterns = [path("localai/", include("localai.urls"))]

from django.contrib.auth.models import AnonymousUser  # noqa: E402
from django.test import Client  # noqa: E402

from localai import client as client_mod  # noqa: E402

JOB = "a" * 32


class FakeGateway:
    def __init__(self):
        self.jobs = {}
        self.deleted = []
        self.down = False

    def submit_generate(self, prompt, system=None, **_):
        if self.down:
            raise client_mod.LocalAIError("down", 503)
        self.jobs[JOB] = {"status": "running", "result": None}
        self.last = (prompt, system)
        return JOB

    def get_job(self, job_id):
        return self.jobs[job_id]

    def delete_job(self, job_id):
        self.deleted.append(job_id)


@pytest.fixture
def gw(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr("localai.views.get_client", lambda: fake)
    return fake


@pytest.fixture
def c(monkeypatch):
    user = type("U", (), {"is_authenticated": True, "is_active": True})()
    monkeypatch.setattr("django.contrib.auth.middleware.get_user", lambda request: user)
    return Client()


def post(c, body):
    return c.post("/localai/jobs/", data=json.dumps(body), content_type="application/json")


def test_login_required(gw, monkeypatch):
    monkeypatch.setattr("django.contrib.auth.middleware.get_user", lambda request: AnonymousUser())
    assert post(Client(), {"prompt": "hi"}).status_code == 302


def test_submit_and_poll_roundtrip(c, gw):
    r = post(c, {"prompt": "요약해줘"})
    assert r.status_code == 202 and r.json()["job_id"] == JOB
    assert gw.last[1]  # fixed server-side system prompt was sent

    assert c.get(f"/localai/jobs/{JOB}/").json() == {"status": "running"}

    gw.jobs[JOB] = {"status": "done", "result": {"response": "결과"}}
    assert c.get(f"/localai/jobs/{JOB}/").json() == {"status": "done", "response": "결과"}
    assert gw.deleted == [JOB]
    # Delivered jobs are forgotten by the session.
    assert c.get(f"/localai/jobs/{JOB}/").status_code == 404


def test_cannot_poll_someone_elses_job(c, gw):
    gw.jobs[JOB] = {"status": "done", "result": {"response": "secret"}}
    assert c.get(f"/localai/jobs/{JOB}/").status_code == 404


def test_validation(c, gw):
    assert post(c, {"prompt": "  "}).status_code == 400
    assert post(c, {"prompt": "x" * 9000}).status_code == 413


def test_laptop_down(c, gw):
    gw.down = True
    r = post(c, {"prompt": "hi"})
    assert r.status_code == 503 and "error" in r.json()


def test_client_maps_gateway_errors(monkeypatch):
    import requests

    cl = client_mod.LocalAIClient("https://x", "k")

    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(cl.session, "request", boom)
    with pytest.raises(client_mod.LocalAIError) as e:
        cl.get_job(JOB)
    assert e.value.status == 503
