#!/usr/bin/env bash
# Local AI API 설치 (Ubuntu 등 systemd 리눅스). 사용: bash scripts/setup_linux.sh [모델]
set -euo pipefail
MODEL="${1:-qwen3.5:4b}"
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# 1) Ollama 설치 (공식 스크립트가 systemd 서비스까지 등록)
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

# 2) Ollama는 127.0.0.1 에서만 listen
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_KEEP_ALIVE=30m"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama

# 3) 모델
ollama pull "$MODEL"
command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv \
  || echo "경고: nvidia-smi 없음 → NVIDIA 드라이버 설치 필요 (없으면 CPU로만 동작)"

# 4) Python 환경
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# 5) .env
if [ ! -f .env ]; then
  KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -e "s|^API_KEYS=.*|API_KEYS=$KEY|" -e "s|^DEFAULT_MODEL=.*|DEFAULT_MODEL=$MODEL|" .env.example > .env
  chmod 600 .env
  echo ".env 생성 완료. API 키: $KEY"
fi

# 6) 게이트웨이를 systemd 서비스로 등록 (부팅 시 자동 시작)
sudo tee /etc/systemd/system/localapi.service >/dev/null <<EOF
[Unit]
Description=Local AI API gateway
After=network-online.target ollama.service
Wants=ollama.service

[Service]
User=$(id -un)
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/python -m gateway
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now localapi
echo "완료! 상태 확인: curl http://127.0.0.1:8000/health"
