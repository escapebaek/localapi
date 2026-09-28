import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.app import Settings, create_app

KEY = "test-key"
H = {"Authorization": f"Bearer {KEY}"}


class FakeOllama:
    def __init__(self):
        self.last_body = None
        self.status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.0.0"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
        if request.url.path == "/api/chat":
            self.last_body = json.loads(request.content)
            if self.status != 200:
                return httpx.Response(self.status, json={"error": "model not found"})
            if self.last_body["stream"]:
                lines = [
                    {"message": {"content": "안녕"}, "done": False},
                    {"message": {"content": "하세요"}, "done": False},
                    {"message": {"content": ""}, "done": True, "done_reason": "stop"},
                ]
                return httpx.Response(200, content="\n".join(json.dumps(l) for l in lines))
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": "echo: " + self.last_body["messages"][-1]["content"]},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 10,
                    "eval_count": 5,
                    "load_duration": 2_000_000_000,
                    "prompt_eval_duration": 500_000_000,
                    "eval_duration": 1_000_000_000,
                },
            )
        return httpx.Response(404)


@pytest.fixture
def fake():
    return FakeOllama()


@pytest.fixture
def client(fake):
    settings = Settings(api_keys=[KEY], allowed_models=["qwen3.5:4b", "qwen3.5:2b"])
    with TestClient(create_app(settings, transport=httpx.MockTransport(fake))) as c:
        yield c


def test_refuses_to_start_without_keys():
    with pytest.raises(RuntimeError):
        create_app(Settings())


def test_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok", "ollama": True}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"X-API-Key": "nope"}])
def test_auth_required(client, headers):
    assert client.post("/v1/generate", json={"prompt": "hi"}, headers=headers).status_code == 401


def test_x_api_key_header(client):
    assert client.post("/v1/generate", json={"prompt": "hi"}, headers={"X-API-Key": KEY}).status_code == 200


def test_generate(client, fake):
    r = client.post("/v1/generate", json={"prompt": "hi", "system": "be brief"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "echo: hi"
    assert body["completion_tokens"] == 5
    assert (body["load_ms"], body["prompt_eval_ms"], body["eval_ms"]) == (2000, 500, 1000)
    sent = fake.last_body
    assert sent["model"] == "qwen3.5:4b"
    assert sent["messages"][0] == {"role": "system", "content": "be brief"}
    assert sent["think"] is False
    assert sent["options"]["num_ctx"] == 4096


def test_num_gpu_only_sent_when_set(client, fake):
    client.post("/v1/generate", json={"prompt": "hi"}, headers=H)
    assert "num_gpu" not in fake.last_body["options"]

    settings = Settings(api_keys=[KEY], num_gpu=0)
    with TestClient(create_app(settings, transport=httpx.MockTransport(fake))) as c:
        c.post("/v1/generate", json={"prompt": "hi"}, headers=H)
    assert fake.last_body["options"]["num_gpu"] == 0


def test_think_and_format_passthrough(client, fake):
    client.post("/v1/generate", json={"prompt": "hi", "think": True, "format": "json", "max_tokens": 99999}, headers=H)
    assert fake.last_body["think"] is True
    assert fake.last_body["format"] == "json"
    assert fake.last_body["options"]["num_predict"] == 4096  # clamped


def test_disallowed_model_rejected(client, fake):
    r = client.post("/v1/generate", json={"prompt": "hi", "model": "gpt-oss:120b-cloud"}, headers=H)
    assert r.status_code == 400
    assert fake.last_body is None


def test_input_limit(client):
    r = client.post("/v1/generate", json={"prompt": "x" * 40_000}, headers=H)
    assert r.status_code == 413


def test_ollama_error_maps_to_502(client, fake):
    fake.status = 404
    r = client.post("/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=H)
    assert r.status_code == 502
    assert "model not found" in r.json()["detail"]


def test_models(client):
    data = client.get("/v1/models", headers=H).json()["data"]
    assert {m["id"]: m["installed"] for m in data} == {"qwen3.5:4b": True, "qwen3.5:2b": False}


def test_jobs_roundtrip(client):
    r = client.post("/v1/jobs/generate", json={"prompt": "slow task"}, headers=H)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    for _ in range(50):
        job = client.get(f"/v1/jobs/{job_id}", headers=H).json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert job["status"] == "done"
    assert job["result"]["response"] == "echo: slow task"
    assert client.delete(f"/v1/jobs/{job_id}", headers=H).status_code == 204
    assert client.get(f"/v1/jobs/{job_id}", headers=H).status_code == 404


def test_openai_compatible(client, fake):
    r = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
            "response_format": {"type": "json_object"},
        },
        headers=H,
    )
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "echo: hi"
    assert body["usage"]["total_tokens"] == 15
    assert fake.last_body["format"] == "json"


def test_openai_streaming(client):
    with client.stream(
        "POST", "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "stream": True}, headers=H
    ) as r:
        events = [l[6:] for l in r.iter_lines() if l.startswith("data: ")]
    assert events[-1] == "[DONE]"
    text = "".join(json.loads(e)["choices"][0]["delta"]["content"] for e in events[:-1])
    assert text == "안녕하세요"
    assert json.loads(events[-2])["choices"][0]["finish_reason"] == "stop"
