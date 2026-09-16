#!/usr/bin/env bash
set -euo pipefail

echo "=================================================="
echo "🚀 [VM Setup] Gemini Chatbot Provisioning Started"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=================================================="

# 1. 패키지 업데이트 및 필수 패키지 설치
echo "📦 [1/6] Installing system packages (python3, pip, venv, curl)..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv curl

# 2. 애플리케이션 디렉터리 구성
APP_DIR="/opt/chatbot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 [2/6] Preparing application directory: ${APP_DIR}..."
sudo mkdir -p "${APP_DIR}"
sudo cp -r "${SCRIPT_DIR}/server.py" "${SCRIPT_DIR}/requirements.txt" "${SCRIPT_DIR}/public" "${APP_DIR}/"

# 3. Python 가상환경 생성 및 패키지 설치
echo "🐍 [3/6] Setting up Python virtual environment..."
cd "${APP_DIR}"
sudo python3 -m venv venv
sudo "${APP_DIR}/venv/bin/pip" install --upgrade pip
sudo "${APP_DIR}/venv/bin/pip" install -r requirements.txt

# 4. Secret Manager에서 GEMINI_API_KEY 조회
echo "🔑 [4/6] Fetching GEMINI_API_KEY from Secret Manager (projects/902882112756/secrets/GEMINI_API_KEY)..."
SECRET_KEY=""
if command -v gcloud &> /dev/null; then
    SECRET_KEY=$(gcloud secrets versions access latest --secret=GEMINI_API_KEY --project=902882112756 2>/dev/null || echo "")
fi

if [ -z "${SECRET_KEY}" ]; then
    echo "⚠️ Warning: Could not fetch secret via gcloud CLI directly. Attempting python secretmanager client..."
    SECRET_KEY=$(sudo "${APP_DIR}/venv/bin/python" -c '
from google.cloud import secretmanager
try:
    client = secretmanager.SecretManagerServiceClient()
    name = "projects/902882112756/secrets/GEMINI_API_KEY/versions/latest"
    res = client.access_secret_version(request={"name": name})
    print(res.payload.data.decode("UTF-8").strip())
except Exception as e:
    print("")
' || echo "")
fi

if [ -n "${SECRET_KEY}" ]; then
    echo "GEMINI_API_KEY=${SECRET_KEY}" | sudo tee "${APP_DIR}/.env" > /dev/null
    sudo chmod 600 "${APP_DIR}/.env"
    echo "✅ Successfully saved GEMINI_API_KEY to ${APP_DIR}/.env"
else
    echo "⚠️ Warning: Secret retrieval returned empty. server.py will fallback to dynamic Secret Manager client at runtime."
fi

# 5. Systemd 서비스 등록
echo "⚙️ [5/6] Configuring systemd service (chatbot.service)..."
cat << 'EOF' | sudo tee /etc/systemd/system/chatbot.service > /dev/null
[Unit]
Description=Gemini Chatbot Web Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/chatbot
EnvironmentFile=-/opt/chatbot/.env
Environment=HOST=0.0.0.0
Environment=PORT=3000
ExecStart=/opt/chatbot/venv/bin/python server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable chatbot.service
sudo systemctl restart chatbot.service

# 6. 서비스 상태 및 헬스체크
echo "🔍 [6/6] Verifying service status..."
sleep 3
sudo systemctl status chatbot.service --no-pager || true

echo "🌐 Testing local endpoint http://127.0.0.1:3000/api/status..."
curl -s http://127.0.0.1:3000/api/status || true

echo ""
echo "=================================================="
echo "🎉 [VM Setup] Gemini Chatbot Provisioning Completed!"
echo "=================================================="
