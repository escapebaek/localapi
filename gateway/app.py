"""Local AI API gateway.

Sits in front of a local Ollama server and adds what Ollama itself lacks
for exposing it to other programs: API-key auth, a model allowlist (so no
request can reach an Ollama cloud model), input limits, a concurrency cap
sized for a small GPU, and an async job API for slow requests.

Prompts and responses are never logged or written to disk; finished jobs
live in memory only and expire after JOB_TTL seconds.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

log = logging.getLogger("localapi")


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _optional_bool(value: str) -> bool | None:
    value = value.strip().lower()
    if value in ("", "none", "auto"):
        return None
    return value in ("1", "true", "yes", "on")


@dataclass
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3.5:4b"
    # Extra models callers may request; default_model is always allowed.
    allowed_models: list[str] = field(default_factory=list)
    api_keys: list[str] = field(default_factory=list)
    allow_no_auth: bool = False
    cors_origins: list[str] = field(default_factory=list)
    # An old GPU runs one generation at a time; extra requests wait their turn.
    max_concurrent: int = 1
    request_timeout: float = 600.0
    num_ctx: int = 4096
    # Layers to offload to the GPU. None = Ollama decides; 0 = CPU only
    # (for GPUs/drivers Ollama's CUDA build can't use).
    num_gpu: int | None = None
    keep_alive: str = "30m"
    # Qwen3/3.5 "thinking" often multiplies latency; off unless asked for.
    # None leaves the model's own default (use for models without thinking).
    default_think: bool | None = False
    max_input_chars: int = 32_000
    max_output_tokens: int = 4096
    job_ttl: int = 3600
    max_jobs: int = 100

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            ollama_url=env("OLLAMA_URL", cls.ollama_url),
            default_model=env("DEFAULT_MODEL", cls.default_model),
            allowed_models=_csv(env("ALLOWED_MODELS", "")),
            api_keys=_csv(env("API_KEYS", "")),
            allow_no_auth=env("ALLOW_NO_AUTH", "false").lower() == "true",
            cors_origins=_csv(env("CORS_ORIGINS", "")),
            max_concurrent=int(env("MAX_CONCURRENT", "1")),
            request_timeout=float(env("REQUEST_TIMEOUT", "600")),
            num_ctx=int(env("NUM_CTX", "4096")),
            num_gpu=int(env("NUM_GPU")) if env("NUM_GPU", "").strip() else None,
            keep_alive=env("KEEP_ALIVE", "30m"),
            default_think=_optional_bool(env("DEFAULT_THINK", "false")),
            max_input_chars=int(env("MAX_INPUT_CHARS", "32000")),
            max_output_tokens=int(env("MAX_OUTPUT_TOKENS", "4096")),
            job_ttl=int(env("JOB_TTL", "3600")),
            max_jobs=int(env("MAX_JOBS", "100")),
        )

    @property
    def models(self) -> list[str]:
        return list(dict.fromkeys([self.default_model, *self.allowed_models]))


# ---------------------------------------------------------------- schemas


class GenOptions(BaseModel):
    model: str | None = None
    think: bool | None = None
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, gt=0)
    # "json" or a JSON schema object for structured output.
    format: Literal["json"] | dict[str, Any] | None = None


class GenerateRequest(GenOptions):
    prompt: str = Field(min_length=1)
    system: str | None = None


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(GenOptions):
    messages: list[Message] = Field(min_length=1)


class OpenAIChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]] = Field(min_length=1)
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, gt=0)
    max_completion_tokens: int | None = Field(None, gt=0)
    stream: bool = False
    response_format: dict[str, Any] | None = None
    # Non-standard extension, same meaning as in /v1/chat.
    think: bool | None = None


@dataclass
class Job:
    id: str
    status: Literal["queued", "running", "done", "error"] = "queued"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


# ---------------------------------------------------------------- core


class Engine:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client
        self.sem = asyncio.Semaphore(settings.max_concurrent)
        self.jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def resolve_model(self, requested: str | None) -> str:
        model = requested or self.settings.default_model
        if model not in self.settings.models:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"model '{model}' is not allowed; allowed: {self.settings.models}",
            )
        return model

    def build_body(
        self, messages: list[dict[str, str]], opts: GenOptions, stream: bool
    ) -> dict[str, Any]:
        s = self.settings
        if sum(len(m["content"]) for m in messages) > s.max_input_chars:
            raise HTTPException(
                413,
                f"input exceeds MAX_INPUT_CHARS ({s.max_input_chars})",
            )
        options: dict[str, Any] = {
            "num_ctx": s.num_ctx,
            "num_predict": min(opts.max_tokens or s.max_output_tokens, s.max_output_tokens),
        }
        if s.num_gpu is not None:
            options["num_gpu"] = s.num_gpu
        if opts.temperature is not None:
            options["temperature"] = opts.temperature
        body: dict[str, Any] = {
            "model": self.resolve_model(opts.model),
            "messages": messages,
            "stream": stream,
            "keep_alive": s.keep_alive,
            "options": options,
        }
        think = opts.think if opts.think is not None else s.default_think
        if think is not None:
            body["think"] = think
        if opts.format is not None:
            body["format"] = opts.format
        return body

    async def chat(
        self, messages: list[dict[str, str]], opts: GenOptions, on_start=None
    ) -> dict[str, Any]:
        body = self.build_body(messages, opts, stream=False)
        async with self.sem:
            if on_start:
                on_start()
            started = time.monotonic()
            try:
                resp = await self.client.post("/api/chat", json=body)
            except httpx.TimeoutException:
                raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "model timed out")
            except httpx.HTTPError:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Ollama is not reachable")
            elapsed_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code != 200:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Ollama error: {_ollama_error(resp)}")
        data = resp.json()
        message = data.get("message") or {}
        return {
            "model": body["model"],
            "response": message.get("content", ""),
            "thinking": message.get("thinking") or None,
            "done_reason": data.get("done_reason"),
            "prompt_tokens": data.get("prompt_eval_count"),
            "completion_tokens": data.get("eval_count"),
            "duration_ms": elapsed_ms,
        }

    async def chat_stream(self, body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        async with self.sem:
            async with self.client.stream("POST", "/api/chat", json=body) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    yield {"error": _ollama_error(resp), "done": True}
                    return
                async for line in resp.aiter_lines():
                    if line.strip():
                        yield json.loads(line)

    # -- jobs

    def _purge_jobs(self) -> None:
        cutoff = time.time() - self.settings.job_ttl
        for job_id in [
            j.id for j in self.jobs.values() if j.finished_at and j.finished_at < cutoff
        ]:
            del self.jobs[job_id]

    def submit(self, messages: list[dict[str, str]], opts: GenOptions) -> Job:
        self._purge_jobs()
        # Validate up front so bad requests fail fast instead of as a job error.
        self.build_body(messages, opts, stream=False)
        if len(self.jobs) >= self.settings.max_jobs:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "job queue is full")
        job = Job(id=uuid.uuid4().hex)
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run_job(job, messages, opts))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run_job(self, job: Job, messages: list[dict[str, str]], opts: GenOptions) -> None:
        try:
            def mark_running() -> None:
                job.status = "running"

            job.result = await self.chat(messages, opts, on_start=mark_running)
            job.status = "done"
        except HTTPException as exc:
            job.status, job.error = "error", str(exc.detail)
        except Exception:
            log.exception("job %s failed", job.id)
            job.status, job.error = "error", "internal error"
        finally:
            job.finished_at = time.time()

    def get_job(self, job_id: str) -> Job:
        self._purge_jobs()
        job = self.jobs.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
        return job


def _ollama_error(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", resp.status_code))
    except ValueError:
        return f"HTTP {resp.status_code}"


def _generate_messages(req: GenerateRequest) -> list[dict[str, str]]:
    messages = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.prompt})
    return messages


def _openai_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # [{"type": "text", "text": ...}, ...]
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


# ---------------------------------------------------------------- app


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.api_keys and not settings.allow_no_auth:
        raise RuntimeError("API_KEYS is empty. Set API_KEYS in .env (or ALLOW_NO_AUTH=true for local testing).")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        timeout = httpx.Timeout(settings.request_timeout, connect=5.0)
        async with httpx.AsyncClient(base_url=settings.ollama_url, timeout=timeout, transport=transport) as client:
            app.state.engine = Engine(settings, client)
            yield

    app = FastAPI(title="Local AI API", version="1.0.0", lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "X-API-Key", "Content-Type"],
        )

    def engine(request: Request) -> Engine:
        return request.app.state.engine

    def require_key(request: Request) -> None:
        if not settings.api_keys:
            return
        key = request.headers.get("x-api-key", "")
        auth = request.headers.get("authorization", "")
        if not key and auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        if not any(secrets.compare_digest(key.encode(), k.encode()) for k in settings.api_keys):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API key")

    auth = [Depends(require_key)]

    @app.get("/health")
    async def health(eng: Engine = Depends(engine)):
        try:
            resp = await eng.client.get("/api/version", timeout=5.0)
            ollama_ok = resp.status_code == 200
        except httpx.HTTPError:
            ollama_ok = False
        return {"status": "ok" if ollama_ok else "degraded", "ollama": ollama_ok}

    @app.get("/v1/models", dependencies=auth)
    async def models(eng: Engine = Depends(engine)):
        installed: set[str] = set()
        try:
            resp = await eng.client.get("/api/tags", timeout=10.0)
            installed = {m["name"] for m in resp.json().get("models", [])}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return {
            "object": "list",
            "default": settings.default_model,
            "data": [
                {"id": m, "object": "model", "owned_by": "local", "installed": m in installed}
                for m in settings.models
            ],
        }

    @app.post("/v1/generate", dependencies=auth)
    async def generate(req: GenerateRequest, eng: Engine = Depends(engine)):
        return await eng.chat(_generate_messages(req), req)

    @app.post("/v1/chat", dependencies=auth)
    async def chat(req: ChatRequest, eng: Engine = Depends(engine)):
        return await eng.chat([m.model_dump() for m in req.messages], req)

    @app.post("/v1/jobs/generate", dependencies=auth, status_code=202)
    async def job_generate(req: GenerateRequest, eng: Engine = Depends(engine)):
        return eng.submit(_generate_messages(req), req).public()

    @app.post("/v1/jobs/chat", dependencies=auth, status_code=202)
    async def job_chat(req: ChatRequest, eng: Engine = Depends(engine)):
        return eng.submit([m.model_dump() for m in req.messages], req).public()

    @app.get("/v1/jobs/{job_id}", dependencies=auth)
    async def job_status(job_id: str, eng: Engine = Depends(engine)):
        return eng.get_job(job_id).public()

    @app.delete("/v1/jobs/{job_id}", dependencies=auth, status_code=204)
    async def job_delete(job_id: str, eng: Engine = Depends(engine)):
        job = eng.get_job(job_id)
        if job.finished_at is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "job is still running")
        del eng.jobs[job_id]

    @app.post("/v1/chat/completions", dependencies=auth)
    async def openai_chat(req: OpenAIChatRequest, eng: Engine = Depends(engine)):
        """OpenAI-compatible endpoint so existing OpenAI SDK code can point here."""
        messages = [
            {"role": m.get("role", "user"), "content": _openai_content(m.get("content"))}
            for m in req.messages
        ]
        if any(m["role"] not in ("system", "user", "assistant") for m in messages):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unsupported message role")
        rf = (req.response_format or {}).get("type")
        schema = (req.response_format or {}).get("json_schema", {}).get("schema")
        opts = GenOptions(
            model=req.model,
            think=req.think,
            temperature=req.temperature,
            max_tokens=req.max_completion_tokens or req.max_tokens,
            format=schema if rf == "json_schema" and schema else ("json" if rf == "json_object" else None),
        )
        cid = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())

        if not req.stream:
            out = await eng.chat(messages, opts)
            return {
                "id": cid,
                "object": "chat.completion",
                "created": created,
                "model": out["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": out["response"]},
                        "finish_reason": "length" if out["done_reason"] == "length" else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": out["prompt_tokens"] or 0,
                    "completion_tokens": out["completion_tokens"] or 0,
                    "total_tokens": (out["prompt_tokens"] or 0) + (out["completion_tokens"] or 0),
                },
            }

        body = eng.build_body(messages, opts, stream=True)

        async def sse() -> AsyncIterator[str]:
            try:
                async for part in eng.chat_stream(body):
                    if "error" in part:
                        yield f"data: {json.dumps({'error': {'message': part['error']}})}\n\n"
                        break
                    done = part.get("done", False)
                    chunk = {
                        "id": cid,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": body["model"],
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": (part.get("message") or {}).get("content", "")},
                                "finish_reason": ("length" if part.get("done_reason") == "length" else "stop") if done else None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            except httpx.HTTPError:
                yield f"data: {json.dumps({'error': {'message': 'Ollama is not reachable'}})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    return app
