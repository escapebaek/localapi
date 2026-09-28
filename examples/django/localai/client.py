"""Thin client for the localapi gateway, used from Django views.

Reads settings.LOCALAI_URL (the Tailscale Funnel URL, e.g.
https://localai.tail1234.ts.net) and settings.LOCALAI_API_KEY.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import requests
from django.conf import settings


class LocalAIError(Exception):
    """Error safe to show to end users; `status` is the HTTP code to return."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


class LocalAIClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = self.session.request(method, self.base_url + path, timeout=self.timeout, **kwargs)
        except requests.RequestException:
            raise LocalAIError("AI 서버(노트북)에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.", 503)
        if resp.status_code == 404:
            raise LocalAIError("작업을 찾을 수 없습니다. 만료되었거나 AI 서버가 재시작되었습니다.", 404)
        if resp.status_code == 429:
            raise LocalAIError("요청이 많이 밀려 있습니다. 잠시 후 다시 시도해 주세요.", 429)
        if resp.status_code == 413:
            raise LocalAIError("입력이 너무 깁니다.", 413)
        if resp.status_code >= 400:
            raise LocalAIError("AI 서버에서 오류가 발생했습니다.", 502)
        return resp.json() if resp.content else {}

    def submit_generate(self, prompt: str, system: str | None = None, **options: Any) -> str:
        """Queue a generation on the gateway and return its job_id immediately."""
        body = {"prompt": prompt, **options}
        if system:
            body["system"] = system
        return self._request("POST", "/v1/jobs/generate", json=body)["job_id"]

    def get_job(self, job_id: str) -> dict[str, Any]:
        """{"status": queued|running|done|error, "result": {...}|None, "error": str|None, ...}"""
        return self._request("GET", f"/v1/jobs/{job_id}")

    def delete_job(self, job_id: str) -> None:
        try:
            self._request("DELETE", f"/v1/jobs/{job_id}")
        except LocalAIError:
            pass  # best effort; the gateway expires jobs on its own


@lru_cache(maxsize=1)
def get_client() -> LocalAIClient:
    return LocalAIClient(settings.LOCALAI_URL, settings.LOCALAI_API_KEY)
