# Windows 노트북 설치 가이드 (qwen3.5:4b)

처음부터 끝까지 순서대로 따라 하면 됩니다. 전체 소요 시간은 30분~1시간이며, 대부분 모델 다운로드(약 3.4GB) 시간입니다.

## 0. 준비물 확인

| 항목 | 확인 방법 |
|---|---|
| Windows 10 (21H2 이상) 또는 11 | `winver` 실행 |
| 디스크 여유 공간 10GB 이상 | 탐색기 → 내 PC |
| `winget` 사용 가능 | PowerShell에서 `winget --version` (없으면 Microsoft Store에서 "앱 설치 관리자" 업데이트) |
| 인터넷 연결 | 설치할 때만 필요. 설치 후 모델 실행은 오프라인으로 동작 |

## 1. NVIDIA 드라이버 업데이트 (GPU 사용을 위해)

1. <https://www.nvidia.com/Download/index.aspx> 에서 **GeForce → GTX 900 Series → GTX 960** 을 선택해 최신 드라이버 설치
2. 설치 후 재부팅
3. PowerShell에서 확인:
   ```powershell
   nvidia-smi
   ```
   표 상단의 `Memory-Usage` 에서 `/ 2048MiB` 또는 `/ 4096MiB` 가 VRAM 크기입니다.
   - **4GB면** `qwen3.5:4b` 로 그대로 진행
   - **2GB면** 4b도 동작은 하지만(GPU+CPU 분할) 느립니다. 테스트 후 느리면 `qwen3.5:2b` 로 변경 (9번 참고)

> 드라이버가 설치되지 않거나 GPU가 인식되지 않아도 **CPU로 동작**합니다. 속도만 느려집니다.

## 2. 프로젝트 내려받기

**방법 A — Git 사용**
```powershell
winget install -e --id Git.Git        # Git이 없을 때만. 설치 후 PowerShell 새 창 열기
cd $HOME
git clone https://github.com/escapebaek/localapi.git
cd localapi
```

**방법 B — ZIP 다운로드**
GitHub 저장소 페이지 → `Code` → `Download ZIP` → `C:\Users\<내이름>\localapi` 에 압축 해제 → PowerShell에서 `cd $HOME\localapi`

> PR이 아직 merge 전이면 브랜치를 지정하세요: `git clone -b claude/determined-meitner-ggkrsc https://github.com/escapebaek/localapi.git`

## 3. 설치 스크립트 실행

`localapi` 폴더에서 (일반 PowerShell, 관리자 아님):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

스크립트가 자동으로 하는 일:
1. Python 3.12 설치 (없을 때만)
2. Ollama 설치 (없을 때만) 및 실행
3. `OLLAMA_HOST=127.0.0.1:11434` 설정 → Ollama를 이 노트북 내부에서만 접근 가능하게
4. `qwen3.5:4b` 모델 다운로드 (약 3.4GB)
5. GPU 정보 출력
6. 게이트웨이용 Python 가상환경(`.venv`) 생성, 라이브러리 설치
7. `.env` 파일 생성 + **랜덤 API 키 발급** (화면에 출력됨, `.env` 안에도 저장됨)

> `Python not found after install` 이 나오면 PowerShell 창을 닫고 새로 연 뒤 같은 명령을 다시 실행하세요.

## 4. Ollama 재시작

작업 표시줄 오른쪽 트레이의 **Ollama(라마) 아이콘 우클릭 → Quit Ollama** → 시작 메뉴에서 **Ollama** 다시 실행.
(3단계의 환경변수를 적용하기 위함)

> Ollama를 실행했을 때 "터미널에서 `ollama`를 입력하세요" 같은 안내 창이나 채팅 창이 떠도 **추가로 설치할 것은 없습니다.** 창은 닫아도 되고, 트레이에 아이콘만 떠 있으면 백그라운드 서버가 동작 중입니다.
> 확인: PowerShell에서 `ollama list` → 목록에 `qwen3.5:4b` 가 보이면 정상.

## 5. 게이트웨이 실행

PowerShell에서 **`localapi` 폴더로 이동한 뒤** 실행합니다. PowerShell은 현재 폴더의 파일을 실행할 때 앞에 `.\` 를 붙여야 합니다.
```powershell
cd $HOME\localapi
.\scripts\start_windows.bat
```
(탐색기에서 `scripts\start_windows.bat` 을 더블클릭해도 됩니다.)

`Uvicorn running on http://127.0.0.1:8000` 이 보이면 성공입니다. 이 창은 켜 둔 채로 다음 단계를 진행하세요.

## 6. 동작 테스트

**새 PowerShell 창**에서:
```powershell
cd $HOME\localapi
powershell -ExecutionPolicy Bypass -File scripts\test_api.ps1
```
정상이라면:
```
== /health
status : ok
ollama : True
== /v1/models
id          installed
qwen3.5:4b       True
== /v1/generate ...
안녕하세요, 저는 ...
-- 23512 ms, 61 output tokens, 2.6 tok/s
```
첫 호출은 모델을 메모리에 올리느라 더 오래 걸립니다. **한 번 더 실행해서 나온 `tok/s` 가 실제 속도**입니다.

GPU를 쓰는지 확인:
```powershell
ollama ps
```
`PROCESSOR` 열이 `100% GPU` 면 전부 GPU, `40%/60% CPU/GPU` 처럼 나오면 일부만 GPU, `100% CPU` 면 GPU 미사용입니다.

### 속도 판단 기준
한국어 답변 한 건 ≈ 300~800 토큰. `tok/s` × 180초 ≥ 필요한 토큰 수 이면 3분 안에 처리됩니다.
- 5 tok/s 이상 → 대부분 요청이 1~3분 안에 처리됨
- 2~5 tok/s → 짧은 요약/추출 위주면 OK, 긴 글은 3분 초과 가능
- 2 tok/s 미만 → `qwen3.5:2b` 로 변경 권장

## 7. 부팅 시 자동 실행 + 절전 해제

**게이트웨이 자동 시작** (PowerShell을 **관리자 권한으로 실행** → `cd $HOME\localapi`):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\autostart_windows.ps1
```
- 로그인할 때마다 창 없이 백그라운드에서 게이트웨이가 켜집니다. 로그: `logs\gateway.log`
- 이제 5단계의 `start_windows.bat` 창은 닫아도 됩니다.
- 해제: 같은 명령 뒤에 `-Remove`
- Ollama는 설치 시 자동 시작에 이미 등록되어 있습니다.

**절전/덮개 설정** (설정 → 시스템 → 전원):
- 화면 끄기: 자유 / **절전 모드: "안 함"** (전원 연결 시)
- 제어판 → 전원 옵션 → "덮개를 닫으면" → 전원 연결 시 **"아무 것도 안 함"**

**자동 로그인** (재부팅 후에도 자동으로 켜지게 하려면): 자동 시작은 로그인 시점에 동작하므로, 정전 등으로 재부팅되면 로그인해야 다시 켜집니다. 필요하면 `netplwiz` 로 자동 로그인을 설정하세요 (보안상 노트북 디스크 암호화와 함께 권장).

## 8. 다른 기기에서 호출하기 (Tailscale)

1. 노트북과 호출할 기기에 <https://tailscale.com/download> 설치 → 같은 계정으로 로그인
2. 노트북에서 IP 확인: `tailscale ip -4` → 예: `100.101.102.103`
3. 노트북의 `.env` 수정: `HOST=100.101.102.103`
4. 게이트웨이 재시작 (자동 시작 등록했다면: 작업 스케줄러에서 `LocalAI-Gateway` 끝내기 → 실행, 또는 재부팅)
5. Windows 방화벽 팝업이 뜨면 **개인 네트워크** 허용
6. 다른 기기에서 테스트:
   ```bash
   curl http://100.101.102.103:8000/health
   ```

## 9. 설정 바꾸기 (`.env`)

메모장으로 `.env` 를 열어 수정 후 게이트웨이를 재시작합니다.

| 하고 싶은 것 | 방법 |
|---|---|
| 2b 모델로 변경 | `ollama pull qwen3.5:2b` 후 `DEFAULT_MODEL=qwen3.5:2b` |
| API 키 추가/교체 | `API_KEYS=키1,키2` (쉼표 구분) |
| 긴 문서 처리 | `NUM_CTX=8192` (느려지고 메모리 더 사용) |
| 어려운 문제에 추론 모드 | 요청 JSON에 `"think": true` (기본은 꺼짐, 켜면 2~5배 느림) |
| 웹사이트(브라우저)에서 직접 호출 | `CORS_ORIGINS=https://내사이트주소` |

## 10. 문제 해결

| 증상 | 해결 |
|---|---|
| `/health` 가 `degraded`, `ollama: False` | Ollama가 꺼져 있음 → 시작 메뉴에서 Ollama 실행 |
| `401 invalid or missing API key` | 헤더 `Authorization: Bearer <키>` 확인, `.env` 의 `API_KEYS` 값과 일치하는지 |
| `400 model ... is not allowed` | 요청의 `model` 값이 `DEFAULT_MODEL`/`ALLOWED_MODELS` 에 없음 |
| `502 Ollama error: model ... not found` | `ollama pull qwen3.5:4b` 실행 |
| `504 model timed out` | 응답이 10분 초과 → `max_tokens` 줄이기, 2b 모델, 또는 `/v1/jobs` 사용 |
| `CUDA error: the provided PTX was compiled with an unsupported toolchain` | NVIDIA 드라이버가 Ollama의 CUDA 버전보다 오래됨 → GTX 960용 최신 드라이버 설치 후 재부팅. 그래도 안 되면 `.env` 에 `NUM_GPU=0` (CPU 전용) 후 게이트웨이 재시작 |
| `ollama ps` 가 `100% CPU` | NVIDIA 드라이버 재설치 후 재부팅. 그래도 안 되면 구형 GPU 미지원일 수 있음(CPU로 계속 사용 가능) |
| 스크립트 실행이 막힘 (`running scripts is disabled`) | 명령 앞에 `powershell -ExecutionPolicy Bypass -File` 을 붙여서 실행 |
