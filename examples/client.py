"""다른 프로그램에서 Local AI API를 호출하는 예시 (표준 라이브러리만 사용).

    LOCALAPI_URL=http://100.x.y.z:8000 LOCALAPI_KEY=... python examples/client.py
"""

import json
import os
import time
import urllib.request

URL = os.environ.get("LOCALAPI_URL", "http://127.0.0.1:8000")
KEY = os.environ["LOCALAPI_KEY"]


def call(method: str, path: str, body: dict | None = None, timeout: float = 600) -> dict:
    req = urllib.request.Request(
        URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


# 1) 동기 호출: 응답이 올 때까지 기다림 (최대 10분)
out = call("POST", "/v1/generate", {
    "system": "너는 개인정보를 요약하는 비서다. 한국어로 3줄 이내로 답한다.",
    "prompt": "다음 메모를 요약해줘: 홍길동, 010-1234-5678, 다음주 화요일 병원 예약 ...",
})
print(out["response"], f"({out['duration_ms']} ms)")

# 2) JSON 형식 강제 (구조화 추출)
out = call("POST", "/v1/generate", {
    "prompt": "이름과 전화번호를 JSON으로 추출: 홍길동 010-1234-5678",
    "format": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "phone": {"type": "string"}},
        "required": ["name", "phone"],
    },
})
print(json.loads(out["response"]))

# 3) 비동기 작업: 오래 걸리는 요청은 job으로 넣고 폴링
job = call("POST", "/v1/jobs/generate", {"prompt": "긴 문서 요약 ..."})
while True:
    job = call("GET", f"/v1/jobs/{job['job_id']}")
    if job["status"] in ("done", "error"):
        break
    time.sleep(3)
print(job["result"]["response"] if job["status"] == "done" else job["error"])
