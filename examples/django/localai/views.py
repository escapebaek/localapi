"""Async-job proxy: the browser talks only to Django, Django talks to the laptop.

POST /localai/jobs/            {"prompt": "..."}  -> 202 {"job_id", "status"}
GET  /localai/jobs/<job_id>/                      -> {"status", "response"?, "error"?}

The API key never reaches the browser, the system prompt is fixed here so
the endpoint can't be used as a general-purpose LLM proxy, and each user
can only poll jobs they created (tracked in their session).
"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .client import LocalAIError, get_client

SESSION_KEY = "localai_jobs"
MAX_TRACKED_JOBS = 20


def _system_prompt() -> str:
    return getattr(settings, "LOCALAI_SYSTEM_PROMPT", "한국어로 간결하고 정확하게 답한다.")


def _max_prompt_chars() -> int:
    return getattr(settings, "LOCALAI_MAX_PROMPT_CHARS", 8000)


@login_required
@require_POST
def submit_job(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "잘못된 요청 형식입니다."}, status=400)
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return JsonResponse({"error": "내용을 입력해 주세요."}, status=400)
    if len(prompt) > _max_prompt_chars():
        return JsonResponse({"error": f"{_max_prompt_chars()}자 이내로 입력해 주세요."}, status=413)

    try:
        job_id = get_client().submit_generate(prompt=prompt, system=_system_prompt())
    except LocalAIError as exc:
        return JsonResponse({"error": exc.message}, status=exc.status)

    jobs = request.session.get(SESSION_KEY, [])
    request.session[SESSION_KEY] = (jobs + [job_id])[-MAX_TRACKED_JOBS:]
    return JsonResponse({"job_id": job_id, "status": "queued"}, status=202)


@login_required
@require_GET
def job_status(request, job_id: str):
    jobs = request.session.get(SESSION_KEY, [])
    if job_id not in jobs:
        return JsonResponse({"error": "작업을 찾을 수 없습니다."}, status=404)

    client = get_client()
    try:
        job = client.get_job(job_id)
    except LocalAIError as exc:
        return JsonResponse({"error": exc.message}, status=exc.status)

    out = {"status": job["status"]}
    if job["status"] in ("done", "error"):
        if job["status"] == "done":
            out["response"] = job["result"]["response"]
        else:
            out["error"] = "AI 처리 중 오류가 발생했습니다."
        # Result delivered: drop it from the laptop's memory and the session.
        client.delete_job(job_id)
        request.session[SESSION_KEY] = [j for j in jobs if j != job_id]
    return JsonResponse(out)
