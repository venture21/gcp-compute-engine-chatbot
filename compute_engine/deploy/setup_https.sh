#!/usr/bin/env bash
set -euo pipefail

echo "=================================================="
echo "🔒 [HTTPS Setup] Automating SSL with sslip.io & Let's Encrypt"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "=================================================="

# 1. IP 주소 및 도메인 결정
VM_IP=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" || echo "136.111.157.64")
IP_DASH=$(echo "${VM_IP}" | tr '.' '-')
PRIMARY_DOMAIN="${IP_DASH}.sslip.io"
SECONDARY_DOMAIN="${VM_IP}.sslip.io"

echo "🎯 External IP: ${VM_IP}"
echo "🌐 Primary Domain: ${PRIMARY_DOMAIN}"
echo "🌐 Secondary Domain: ${SECONDARY_DOMAIN}"

# 2. Nginx 및 Certbot 패키지 설치 확인
echo "📦 [1/4] Ensuring nginx & certbot are installed..."
sudo apt-get update -y
sudo apt-get install -y nginx certbot python3-certbot-nginx

# 3. Nginx 역방향 프록시(Reverse Proxy) 설정
echo "⚙️ [2/4] Configuring Nginx reverse proxy for FastAPI chatbot (port 3000)..."
cat << EOF | sudo tee /etc/nginx/sites-available/chatbot > /dev/null
server {
    listen 80;
    listen [::]:80;
    server_name ${PRIMARY_DOMAIN} ${SECONDARY_DOMAIN} ${VM_IP};

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # 타임아웃 넉넉하게 설정 (LLM 긴 스트리밍 및 응답 대기)
        proxy_connect_timeout 60s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
}
EOF

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/chatbot /etc/nginx/sites-enabled/chatbot

sudo nginx -t
sudo systemctl restart nginx

# 4. Let's Encrypt 공인 SSL 인증서 발급
echo "📜 [3/4] Requesting Let's Encrypt SSL certificate for ${PRIMARY_DOMAIN}..."
sudo certbot --nginx \
    -d "${PRIMARY_DOMAIN}" \
    --non-interactive \
    --agree-tos \
    --register-unsafely-without-email \
    --redirect

# 5. Nginx 최종 재기동 및 상태 확인
echo "🔍 [4/4] Verifying Nginx & SSL configuration..."
sudo systemctl reload nginx

echo ""
echo "=================================================="
echo "🎉 [HTTPS Setup Completed Successfully!]"
echo "🌐 HTTPS URL: https://${PRIMARY_DOMAIN}"
echo "=================================================="
