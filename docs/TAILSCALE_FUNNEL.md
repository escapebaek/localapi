# Tailscale Funnel로 노트북 API를 HTTPS로 공개하기

Render 같은 외부 서버(Django)가 집에 있는 노트북 게이트웨이를 호출할 수 있게 합니다.

```
유저 브라우저 ──HTTPS──▶ Django (Render) ──HTTPS(Funnel)──▶ 노트북 게이트웨이(127.0.0.1:8000) ──▶ Ollama
                          API 키는 Render 환경변수에만                  │
                                                        Tailscale이 TLS를 노트북에서 종료
```

- 공유기 포트포워딩이 필요 없고, HTTPS 인증서도 Tailscale이 자동으로 발급합니다.
- Funnel 트래픽의 TLS는 **노트북에서** 풀립니다. Tailscale 중계 서버는 내용을 볼 수 없습니다.
- 게이트웨이는 계속 `HOST=127.0.0.1` 로 둡니다. Funnel이 노트북 내부에서 게이트웨이로 연결해 주므로, 노트북의 다른 포트는 전혀 열리지 않습니다.
- ⚠️ Funnel 주소는 **인터넷 전체에 공개**됩니다. API 키가 유일한 보호막이므로 아래 5단계를 꼭 지키세요.

---

## 1. Tailscale 설치 (노트북)

**방법 A — winget (PowerShell)**
```powershell
winget install -e --id Tailscale.Tailscale
```
**방법 B — 설치 파일**: <https://tailscale.com/download/windows> 에서 받아 실행

설치가 끝나면 작업 표시줄 트레이에 Tailscale 아이콘이 생기고 로그인 창이 뜹니다.

## 2. 로그인

1. 트레이 아이콘 클릭 → **Log in** → 브라우저에서 Google / Microsoft / GitHub 계정 중 하나로 로그인
   (처음 로그인하면 내 계정 전용 네트워크, 즉 "tailnet" 이 자동으로 만들어집니다. 개인용은 무료)
2. PowerShell에서 연결 확인:
   ```powershell
   tailscale status
   ```
   첫 줄에 노트북 이름과 `100.x.y.z` IP가 보이면 성공입니다.

## 3. 관리자 콘솔 설정 (브라우저, 한 번만)

<https://login.tailscale.com/admin> 에 같은 계정으로 접속합니다.

**3-1. 노트북 이름 정하기** (공개 주소에 들어감)
- **Machines** 탭 → 노트북 행 오른쪽 `⋯` → **Edit machine name…** → 예: `localai`
- 공개 주소가 `https://localai.<tailnet이름>.ts.net` 이 됩니다.

**3-2. 키 만료 끄기** (중요: 안 끄면 약 180일 후 연결이 끊김)
- **Machines** 탭 → 노트북 행 `⋯` → **Disable key expiry**

**3-3. HTTPS 인증서 켜기**
- **DNS** 탭 → **MagicDNS** 가 켜져 있는지 확인 → 아래 **HTTPS Certificates** 에서 **Enable HTTPS**

**3-4. Funnel 허용**
- 대부분 다음 단계에서 명령을 처음 실행할 때 "Funnel이 꺼져 있으니 이 링크에서 켜라" 는 안내와 링크가 나옵니다. 그 링크를 열어 허용하면 됩니다.
- 안내가 없고 오류만 나면: **Access controls** 탭의 정책(JSON)에 아래 `nodeAttrs` 가 있는지 확인하고 없으면 추가 후 저장:
  ```json
  "nodeAttrs": [
    { "target": ["autogroup:member"], "attr": ["funnel"] }
  ]
  ```

## 4. Funnel 켜기

게이트웨이가 실행 중인 상태에서(`http://127.0.0.1:8000/health` 가 열리는 상태) PowerShell에서:
```powershell
tailscale funnel --bg 8000
```
- `--bg` : 백그라운드로 켜고, **재부팅 후에도 설정이 유지**됩니다.
- 출력에 공개 주소가 표시됩니다. 예:
  ```
  Available on the internet:
  https://localai.tail1234.ts.net/
  |-- proxy http://127.0.0.1:8000
  ```

확인 명령:
```powershell
tailscale funnel status          # 현재 공개 상태
```

**외부에서 테스트** — 휴대폰의 **Wi-Fi를 끄고(LTE/5G)** 브라우저에서:
```
https://localai.tail1234.ts.net/health
```
`{"status":"ok","ollama":true}` 가 보이면 성공입니다. 처음 켠 직후에는 DNS 전파로 1~10분 걸릴 수 있습니다.

끄기:
```powershell
tailscale funnel reset
```

## 5. 보안 설정 (공개 전에 꼭)

**5-1. Render 전용 API 키를 따로 발급**
```powershell
cd $HOME\localapi
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```
나온 값을 `.env` 의 `API_KEYS` 에 쉼표로 추가합니다 (기존 키는 노트북 테스트용으로 유지):
```
API_KEYS=기존키,새로만든Render용키
```
→ 게이트웨이 재시작. 나중에 키가 유출되면 그 키만 지우면 됩니다.

**5-2. 키는 Render 환경변수에만**: 코드, Git, 프론트엔드 JS에 절대 넣지 마세요.

**5-3. `.env` 에서 확인할 것**
| 항목 | 값 | 이유 |
|---|---|---|
| `HOST` | `127.0.0.1` | Funnel이 내부에서 연결하므로 외부 IP로 열 필요 없음 |
| `ENABLE_DOCS` | `false` | API 문서 페이지(`/docs`)를 인터넷에 노출하지 않음 |
| `CORS_ORIGINS` | (비움) | 브라우저가 아니라 Django 서버가 호출하므로 불필요 |

**5-4. Tailscale 로그인 계정에 2단계 인증(2FA)** 을 켜두세요. 이 계정이 뚫리면 공개 설정도 바뀔 수 있습니다.

## 6. 항상 켜두기

- Tailscale은 Windows 서비스로 설치되어 부팅 시 자동 시작됩니다.
- 로그아웃 상태에서도 연결을 유지하려면: 트레이 아이콘 → **Preferences** → **Run unattended** 체크 (메뉴 이름은 버전에 따라 조금 다를 수 있음)
- 게이트웨이 자동 시작은 [`INSTALL_WINDOWS.md` 7단계](INSTALL_WINDOWS.md#7-부팅-시-자동-실행--절전-해제) 참고
- 노트북이 꺼지거나 절전에 들어가면 Render에서 `AI 서버(노트북)에 연결할 수 없습니다` 오류가 납니다 (Django 예제가 503으로 처리).

## 7. Render(Django)에 넣을 값

Render 대시보드 → 서비스 → **Environment** 에 추가:

| Key | Value |
|---|---|
| `LOCALAI_URL` | `https://localai.tail1234.ts.net` (4단계에서 나온 주소, 끝의 `/` 없이) |
| `LOCALAI_API_KEY` | 5-1에서 만든 Render용 키 |

Django 코드 연결 방법: [`examples/django/README.md`](../examples/django/README.md)

## 문제 해결

| 증상 | 해결 |
|---|---|
| `Funnel is not enabled` / 링크 안내 | 출력된 링크를 열어 허용, 또는 3-4의 `nodeAttrs` 추가 |
| `HTTPS is not enabled` | 3-3 (DNS 탭 → Enable HTTPS) |
| 외부에서 접속 안 됨, 노트북에선 됨 | 1~10분 대기(DNS), 휴대폰 Wi-Fi 끄고 재시도, `tailscale funnel status` 확인 |
| `502 Bad Gateway` | 게이트웨이가 꺼져 있음 → `.\scripts\start_windows.bat` |
| `401 invalid or missing API key` | Render의 `LOCALAI_API_KEY` 와 노트북 `.env` 의 `API_KEYS` 비교 |
| 몇 달 뒤 갑자기 연결 끊김 | 3-2 키 만료 끄기를 안 한 경우 → 트레이에서 다시 로그인 후 키 만료 끄기 |
