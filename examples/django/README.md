# Django(Render) 연동 예제 — 비동기 job 방식

```
브라우저 ──(1) POST /localai/jobs/ {"prompt"}──▶ Django ──POST /v1/jobs/generate──▶ 노트북
        ◀── 202 {"job_id"} ──────────────────────
브라우저 ──(2) 3초마다 GET /localai/jobs/<id>/──▶ Django ──GET /v1/jobs/<id>──────▶ 노트북
        ◀── {"status":"running"} … {"status":"done","response":"..."}
```

- 요청 하나에 1~3분 걸려도 **각 HTTP 요청은 1초 이내**로 끝나서 브라우저·Render의 요청 제한 시간에 걸리지 않습니다.
- 노트북 GPU는 한 번에 한 건만 처리하므로, 여러 유저가 동시에 보내면 순서대로 처리됩니다 (`status: queued` → `running` → `done`).
- API 키는 Django 서버에만 있고 브라우저로 나가지 않습니다.
- 로그인한 유저만 사용 가능하고(`@login_required`), 각 유저는 **자기가 만든 job만** 조회할 수 있습니다.
- 시스템 프롬프트는 서버에 고정되어 있어서, 이 엔드포인트를 범용 AI 프록시로 악용할 수 없습니다.

## 1. 파일 복사

`examples/django/localai/` 폴더를 Django 프로젝트 안(`manage.py` 옆)에 통째로 복사합니다.

```
myproject/
├─ manage.py
├─ myproject/settings.py
└─ localai/            ← 복사
   ├─ client.py         게이트웨이 호출 클라이언트
   ├─ views.py          job 등록 / 조회 뷰
   ├─ urls.py
   └─ static/localai/localai.js   프론트엔드 폴링 함수
```

`requests` 가 없다면 `requirements.txt` 에 추가: `requests>=2.31`

## 2. settings.py

```python
import os

INSTALLED_APPS = [
    # ...
    "localai",
]

LOCALAI_URL = os.environ["LOCALAI_URL"]          # https://localai.tail1234.ts.net
LOCALAI_API_KEY = os.environ["LOCALAI_API_KEY"]

# 선택
LOCALAI_SYSTEM_PROMPT = "너는 개인 메모를 정리하는 비서다. 한국어로 간결하게 답한다."
LOCALAI_MAX_PROMPT_CHARS = 8000
```
Render 환경변수 설정은 [`docs/TAILSCALE_FUNNEL.md` 7단계](../../docs/TAILSCALE_FUNNEL.md#7-renderdjango에-넣을-값) 참고.

## 3. urls.py (프로젝트)

```python
from django.urls import include, path

urlpatterns = [
    # ...
    path("localai/", include("localai.urls")),
]
```

## 4. 템플릿에서 사용

```html
{% load static %}
<textarea id="prompt"></textarea>
<button id="ask">보내기</button>
<p id="status"></p>
<pre id="answer"></pre>

<script src="{% static 'localai/localai.js' %}"></script>
<script>
  document.getElementById("ask").onclick = async () => {
    const statusEl = document.getElementById("status");
    const answerEl = document.getElementById("answer");
    answerEl.textContent = "";
    try {
      const answer = await askLocalAI(document.getElementById("prompt").value, {
        onStatus: (s, sec) =>
          (statusEl.textContent = { queued: "대기 중", running: "처리 중", done: "완료" }[s] + ` · ${sec}초`),
      });
      answerEl.textContent = answer;
    } catch (e) {
      statusEl.textContent = e.message;
    }
  };
</script>
```
페이지에 CSRF 쿠키가 있어야 합니다. 폼이 없는 페이지라면 뷰에 `@ensure_csrf_cookie` 를 붙이세요.

## 5. 서버 코드에서 직접 쓰기 (뷰 없이)

Celery 작업이나 관리 명령 등에서:
```python
import time
from localai.client import get_client

client = get_client()
job_id = client.submit_generate("다음 문서를 요약해줘: ...", system="한국어로 3줄 요약")
while (job := client.get_job(job_id))["status"] not in ("done", "error"):
    time.sleep(3)
print(job["result"]["response"])
client.delete_job(job_id)
```

## 동작 참고

| 상황 | Django 응답 |
|---|---|
| 노트북 꺼짐 / 게이트웨이 꺼짐 | 503 `AI 서버(노트북)에 연결할 수 없습니다…` |
| 대기열 가득 참 (`MAX_JOBS`) | 429 |
| 게이트웨이 재시작으로 job 사라짐, 1시간(`JOB_TTL`) 초과 | 404 |
| 결과 전달 완료 | 노트북 메모리에서 결과 즉시 삭제 |

프라이버시 참고: 이 구조에서는 Render(Django) 서버도 요청 내용을 평문으로 다룹니다. Django 쪽에서 프롬프트/응답을 DB나 로그에 남기지 않도록 주의하세요.
