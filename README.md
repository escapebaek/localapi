# localapi — 내 노트북에서 돌리는 개인용 AI API

개인정보·민감정보를 외부 AI 서비스로 보내지 않고, **집에 켜둔 노트북의 오픈소스 모델(Qwen)** 로 처리하는 HTTP API입니다.

```
[내 프로그램 / 웹사이트 서버]
        │  HTTPS or Tailscale(암호화), API 키
        ▼
┌─────────────── 노트북 ───────────────┐
│  gateway (FastAPI, :8000)           │  ← 인증, 모델 허용목록, 입력 제한,
│        │ 127.0.0.1 only             │    대기열(동시 1건), 비동기 job
│        ▼                            │
│  Ollama (:11434, 외부 비공개)        │  ← Qwen3.5 모델 실행 (GPU+CPU)
└─────────────────────────────────────┘
```

- **Ollama**: 모델 다운로드·실행 엔진. 이 PC 내부(`127.0.0.1`)에서만 열어둡니다.
- **gateway**: Ollama 앞단의 얇은 API 서버. Ollama 자체엔 인증이 없어서 이걸 통해서만 외부에 노출합니다.
- 프롬프트/응답은 **로그나 디스크에 저장하지 않습니다.** 비동기 job 결과만 메모리에 최대 `JOB_TTL`(기본 1시간) 보관 후 삭제됩니다.
- `ALLOWED_MODELS` 허용목록 밖의 모델은 거부합니다 → 실수로 Ollama **클라우드 모델**(`*-cloud`, 외부 서버에서 실행됨)을 호출하는 일을 막습니다.

## 1. 모델 선택 (GTX 960 + RAM 16GB 기준)

먼저 VRAM 확인: `nvidia-smi` 실행 → `Memory` 항목이 2048MiB 또는 4096MiB 입니다.

| 모델 | 크기 | 추천 상황 | 예상 속도* |
|---|---|---|---|
| **`qwen3.5:4b`** (기본값) | 3.4GB | VRAM 4GB. 요약·추출·분류·교정 등 대부분의 작업 | GPU 대부분 적재, 수~십수 tok/s |
| `qwen3.5:2b` | 2.7GB | VRAM 2GB이거나 더 빠른 응답이 필요할 때 | 4b보다 빠름, 품질 약간 낮음 |
| `qwen3.5:9b` | 6.6GB | 품질 우선, 느려도 됨 | 대부분 CPU/RAM에서 실행, 2~4 tok/s 수준 |

\* 추정치입니다. 실제 속도는 `ollama run qwen3.5:4b --verbose` 로 `eval rate` 를 확인하세요.
**1~3분 내 처리**가 목표라면: 한국어 기준 답변 500~1000토큰 × 속도로 계산해 보면 됩니다. 4b가 대부분 이 범위에 들어오고, 9b는 긴 답변이면 3분을 넘길 수 있습니다.

속도 팁
- **thinking(추론) 모드는 기본 OFF** (`DEFAULT_THINK=false`). Qwen3.5는 켜면 답하기 전에 긴 사고 과정을 생성해서 2~5배 느려집니다. 어려운 문제만 요청에 `"think": true`.
- `NUM_CTX`(기본 4096)는 입력+출력 합산 길이입니다. 긴 문서를 넣으려면 8192로 올리되 VRAM 사용량과 속도가 같이 늘어납니다.
- GTX 960(Maxwell)은 오래된 GPU라 최신 Ollama의 CUDA 빌드가 인식하지 못할 수도 있습니다. 그 경우 CPU로 자동 동작합니다(느리지만 작동). `ollama ps` 의 `PROCESSOR` 열에서 GPU 사용 비율을 확인하세요.

## 2. 설치

### Windows — 👉 단계별 가이드: [`docs/INSTALL_WINDOWS.md`](docs/INSTALL_WINDOWS.md)
```powershell
git clone https://github.com/escapebaek/localapi.git; cd localapi
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1            # Python·Ollama·모델·.env 자동 설정
# 트레이의 Ollama 아이콘 → Quit 후 다시 실행 (OLLAMA_HOST 설정 적용)
.\scripts\start_windows.bat                                                  # 게이트웨이 실행
powershell -ExecutionPolicy Bypass -File scripts\test_api.ps1                # (새 창) 동작·속도 확인
powershell -ExecutionPolicy Bypass -File scripts\autostart_windows.ps1       # (관리자) 로그인 시 자동 시작
```

### Linux (Ubuntu 등)
```bash
git clone <이 저장소> localapi && cd localapi
bash scripts/setup_linux.sh            # 또는: bash scripts/setup_linux.sh qwen3.5:2b
```
Ollama + 게이트웨이 모두 systemd 서비스로 등록되어 부팅 시 자동 시작됩니다.

### 동작 확인
```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/generate \
  -H "Authorization: Bearer <.env의 API_KEYS 값>" -H "Content-Type: application/json" \
  -d '{"prompt":"안녕? 한 문장으로 자기소개 해줘"}'
```
첫 요청은 모델을 메모리에 올리느라 10~30초 더 걸립니다. 이후 `KEEP_ALIVE`(30분) 동안은 바로 응답합니다.

## 3. 다른 기기에서 호출하기 (Tailscale)

게이트웨이는 기본적으로 `127.0.0.1`(노트북 자신)에서만 열립니다. 다른 기기에서 쓰려면 둘 중 하나를 고릅니다.

**A. 웹 서비스(Render의 Django 등)에서 호출 — Tailscale Funnel** 👉 [`docs/TAILSCALE_FUNNEL.md`](docs/TAILSCALE_FUNNEL.md)
- 노트북에 `https://localai.xxx.ts.net` 같은 HTTPS 공개 주소를 만들어 줍니다. Render 쪽엔 설치할 것이 없습니다.
- Django 연동 코드(비동기 job + 프론트 폴링): [`examples/django/`](examples/django/README.md)

**B. 내 기기끼리만 — Tailscale 사설망** (인터넷에 공개하지 않음)
1. 노트북과 호출할 기기(내 PC, 폰 등)에 Tailscale 설치 후 같은 계정으로 로그인
2. 노트북의 Tailscale IP 확인(`tailscale ip -4`, `100.x.y.z`)
3. `.env` 에서 `HOST=100.x.y.z` 로 바꾸고 게이트웨이 재시작
4. 다른 기기에서 `http://100.x.y.z:8000/v1/...` 호출

인터넷에 포트를 열지 않고, 기기 간 트래픽은 WireGuard로 종단간 암호화됩니다. 공유기 포트포워딩으로 공개하는 것은 권장하지 않습니다(노출 시 반드시 HTTPS 리버스 프록시 + 강한 API 키).

**웹사이트에서 호출할 때**
- 가장 안전한 구조: 웹사이트의 **백엔드 서버**가 노트북을 호출 → 결과를 프론트에 전달 (A 방식). API 키가 브라우저에 노출되지 않습니다.
- 브라우저 JS에서 직접 호출하려면 `.env` 의 `CORS_ORIGINS` 에 사이트 주소를 추가해야 하며, 이 경우 페이지를 보는 사람이 API 키를 볼 수 있다는 점에 유의하세요(내 기기에서만 쓰는 개인 페이지라면 괜찮음).

## 4. API

모든 `/v1/*` 요청은 헤더 `Authorization: Bearer <키>` 또는 `X-API-Key: <키>` 필요.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 상태 확인 (인증 불필요) |
| GET | `/v1/models` | 허용 모델 목록 + 설치 여부 |
| POST | `/v1/generate` | 단일 프롬프트 → 응답 (응답 올 때까지 대기) |
| POST | `/v1/chat` | 대화 형식 (`messages`) |
| POST | `/v1/jobs/generate`, `/v1/jobs/chat` | 비동기 작업 등록 → `job_id` 즉시 반환 (202) |
| GET / DELETE | `/v1/jobs/{job_id}` | 작업 상태·결과 조회 / 삭제 |
| POST | `/v1/chat/completions` | **OpenAI 호환** (스트리밍 지원). OpenAI SDK에서 `base_url` 만 바꾸면 됨 |

**`/v1/generate` 요청 예시**
```json
{
  "prompt": "다음 진료기록을 3줄로 요약: ...",
  "system": "한국어로 간결하게 답한다.",
  "model": "qwen3.5:4b",       // 생략 시 DEFAULT_MODEL
  "think": false,              // 생략 시 DEFAULT_THINK
  "temperature": 0.3,
  "max_tokens": 800,
  "format": "json"             // 또는 JSON 스키마 객체 → 구조화된 출력
}
```
**응답**
```json
{"model":"qwen3.5:4b","response":"...","thinking":null,"done_reason":"stop",
 "prompt_tokens":120,"completion_tokens":85,"duration_ms":14230}
```

**언제 job을 쓰나?** GPU가 한 번에 한 요청만 처리(`MAX_CONCURRENT=1`)하므로, 여러 요청이 몰리면 뒤 요청은 대기합니다. 대기+처리 시간이 호출 측 HTTP 타임아웃(브라우저·서버리스 함수 등)보다 길어질 수 있으면 `/v1/jobs/*` 로 등록하고 몇 초 간격으로 폴링하세요.

사용 예시 코드: [`examples/client.py`](examples/client.py), [`examples/client.js`](examples/client.js)

## 5. 설정 (`.env`)

전체 항목과 설명은 [`.env.example`](.env.example) 참고. 주요 항목:

| 키 | 기본값 | 설명 |
|---|---|---|
| `API_KEYS` | (필수) | 쉼표로 여러 키 가능. 비어 있으면 서버가 시작을 거부 |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | 외부 호출 시 Tailscale IP로 변경 |
| `DEFAULT_MODEL` | `qwen3.5:4b` | |
| `ALLOWED_MODELS` | | 추가로 허용할 모델 (먼저 `ollama pull` 필요) |
| `DEFAULT_THINK` | `false` | `true` / `false` / 빈 값(모델 기본값, thinking 미지원 모델용) |
| `NUM_CTX` | `4096` | 컨텍스트 길이 |
| `CORS_ORIGINS` | | 브라우저 직접 호출 허용 도메인 |

## 6. 항상 켜두기 (노트북)

- **절전 해제**: Windows 설정 → 전원 → 화면/절전 "안 함", 덮개 닫을 때 "아무 것도 안 함" (Linux: `/etc/systemd/logind.conf` 의 `HandleLidSwitch=ignore`)
- **Windows 자동 시작**: 관리자 PowerShell에서 `scripts\autostart_windows.ps1` → 로그인 시 창 없이 게이트웨이 실행(로그: `logs\gateway.log`). Ollama는 설치 시 자동 시작에 등록됩니다.
- 배터리 상시 충전은 배터리 부풀음 위험이 있으니, 제조사 유틸의 "충전 한도(60~80%)" 기능이 있다면 켜두세요.

## 7. 프라이버시 체크리스트

- [x] 모델 추론은 노트북에서만 실행 (Ollama 로컬 모델)
- [x] Ollama 포트는 `127.0.0.1` 전용, 외부에는 인증된 게이트웨이만 노출
- [x] 클라우드 모델 호출 차단 (모델 허용목록)
- [x] 프롬프트/응답 비저장 (접속 로그엔 경로·상태코드만 기록, `ACCESS_LOG=false` 로 끌 수 있음)
- [ ] 노트북 ↔ 호출 기기 구간은 **Tailscale 또는 HTTPS로 암호화** — 직접 설정 필요
- [ ] 노트북 디스크 암호화(BitLocker / LUKS) 권장

## 개발

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q      # Ollama 없이 모의 서버로 테스트
```
