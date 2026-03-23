#!/bin/bash
set -e

NGINX_CONF_SRC="$(dirname "$0")/nginx.conf"
NGINX_SITE_NAME="ainews"
NGINX_AVAILABLE="/etc/nginx/sites-available/$NGINX_SITE_NAME"
NGINX_ENABLED="/etc/nginx/sites-enabled/$NGINX_SITE_NAME"
ENV_FILE="$(dirname "$0")/.env"

echo "============================================"
echo "  AI & Tech Daily — HTTPS Setup with Nginx"
echo "============================================"
echo ""

# 1. Install nginx and certbot
echo "[1/7] Installing nginx, certbot, and certbot-nginx plugin..."
apt install -y nginx certbot python3-certbot-nginx
echo "     Done."
echo ""

# 2. Ask for domain name
read -p "[2/7] Enter your domain name (e.g. ainews.example.com): " DOMAIN_NAME
if [ -z "$DOMAIN_NAME" ]; then
    echo "ERROR: Domain name cannot be empty."
    exit 1
fi
echo "     Using domain: $DOMAIN_NAME"
echo ""

# 3. Copy nginx config and replace placeholder
echo "[3/7] Installing nginx config..."
cp "$NGINX_CONF_SRC" "$NGINX_AVAILABLE"
sed -i "s/YOUR_DOMAIN_HERE/$DOMAIN_NAME/g" "$NGINX_AVAILABLE"

# Create symlink if it doesn't exist
if [ ! -L "$NGINX_ENABLED" ]; then
    ln -s "$NGINX_AVAILABLE" "$NGINX_ENABLED"
fi

# Remove default site if present
if [ -L /etc/nginx/sites-enabled/default ]; then
    rm /etc/nginx/sites-enabled/default
fi
echo "     Config installed at $NGINX_AVAILABLE"
echo ""

# 4. Test nginx config
echo "[4/7] Testing nginx configuration..."
nginx -t
echo "     Nginx config OK."
echo ""

# Reload nginx before certbot (it needs to answer HTTP challenge)
systemctl reload nginx

# 5. Get SSL certificate
echo "[5/7] Obtaining SSL certificate from Let's Encrypt..."
certbot --nginx -d "$DOMAIN_NAME" -d "www.$DOMAIN_NAME" --non-interactive --agree-tos --redirect
echo "     Certificate obtained."
echo ""

# 6. Reload nginx with new SSL config
echo "[6/7] Reloading nginx..."
systemctl reload nginx
echo "     Nginx reloaded."
echo ""

# 7. Update SITE_URL in .env
echo "[7/7] Updating SITE_URL in .env..."
if [ -f "$ENV_FILE" ]; then
    if grep -q "^SITE_URL=" "$ENV_FILE"; then
        sed -i "s|^SITE_URL=.*|SITE_URL=https://$DOMAIN_NAME|" "$ENV_FILE"
    else
        echo "SITE_URL=https://$DOMAIN_NAME" >> "$ENV_FILE"
    fi
    echo "     SITE_URL set to https://$DOMAIN_NAME"
else
    echo "     WARNING: .env file not found. Create it and add:"
    echo "     SITE_URL=https://$DOMAIN_NAME"
fi
echo ""

echo "============================================"
echo "  Setup complete!"
echo "  Your site is live at: https://$DOMAIN_NAME"
echo ""
echo "  Certbot auto-renewal is configured."
echo "  Test renewal with: certbot renew --dry-run"
echo "============================================"
