#!/bin/bash
set -e

NGINX_SITE_NAME="ainews"
NGINX_AVAILABLE="/etc/nginx/sites-available/$NGINX_SITE_NAME"
NGINX_ENABLED="/etc/nginx/sites-enabled/$NGINX_SITE_NAME"
STATIC_PATH="$(realpath "$(dirname "$0")/static")"

echo "============================================"
echo "  AI & Tech Daily — HTTP-only Nginx Proxy"
echo "  (No domain / No SSL — testing mode)"
echo "============================================"
echo ""

# 1. Install nginx
echo "[1/4] Installing nginx..."
apt install -y nginx
echo "     Done."
echo ""

# 2. Write a minimal nginx config (HTTP only, any hostname)
echo "[2/4] Writing nginx config..."
cat > "$NGINX_AVAILABLE" <<NGINXCONF
server {
    listen 80 default_server;
    server_name _;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/json application/javascript text/javascript image/svg+xml;

    location /static/ {
        alias ${STATIC_PATH}/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
    }

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
}
NGINXCONF
echo "     Config written."
echo ""

# 3. Enable site and remove default
if [ ! -L "$NGINX_ENABLED" ]; then
    ln -s "$NGINX_AVAILABLE" "$NGINX_ENABLED"
fi
if [ -L /etc/nginx/sites-enabled/default ]; then
    rm /etc/nginx/sites-enabled/default
fi

# 4. Test and reload
echo "[3/4] Testing nginx config..."
nginx -t
echo "     OK."
echo ""

echo "[4/4] Reloading nginx..."
systemctl reload nginx
echo "     Done."
echo ""

SERVER_IP=$(hostname -I | awk '{print $1}')
echo "============================================"
echo "  Setup complete!"
echo "  Your site is accessible at: http://$SERVER_IP"
echo ""
echo "  NOTE: This is HTTP only (no SSL)."
echo "  For production use, run setup_https.sh"
echo "  once you have a domain name."
echo "============================================"
