#!/usr/bin/env bash
# deploy-ecs.sh — 在阿里云 ECS 上执行（Ubuntu/Debian/CentOS 通用）
# 用法: sudo bash deploy-ecs.sh
set -e
APP_DIR=${APP_DIR:-/opt/mira-cafe}
PORT=${PORT:-8000}

echo "== [1/4] 拉取代码 =="
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone https://github.com/xjr-git/mira-cafe.git "$APP_DIR"
fi
cd "$APP_DIR"

echo "== [2/4] 安装依赖 =="
if command -v docker >/dev/null 2>&1; then
  echo "docker detected -> docker compose up -d --build"
  docker compose up -d --build
  echo "app listening on 0.0.0.0:$PORT (container)"
  exit 0
fi
command -v python3 >/dev/null || { echo "need python3"; exit 1; }
python3 -m venv .venv 2>/dev/null || apt-get install -y python3-venv >/dev/null
.venv/bin/python -m pip install -q -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

echo "== [3/4] 启动服务 =="
pkill -f "uvicorn app.main:app" 2>/dev/null || true
cd backend
MIRA_PORT=$PORT nohup ../.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port "$PORT" >> "$APP_DIR/mira.log" 2>&1 &
sleep 2
curl -sf "http://127.0.0.1:$PORT/api/state" && echo " <- app OK"

echo "== [4/4] 完成。下一步：nginx 反代（HTTPS 必需，麦克风权限） =="
cat <<'NGINX'
# 在已有 nginx 配置目录新建 /etc/nginx/conf.d/mira.conf（证书路径改成你现有的）：
# server {
#   listen 8843 ssl;
#   server_name <你的域名>;
#   ssl_certificate     <你的证书fullchain>;
#   ssl_certificate_key <你的证书key>;
#   location / {
#     proxy_pass http://127.0.0.1:8000;
#     proxy_http_version 1.1;
#     proxy_set_header Connection "";
#     proxy_buffering off;              # SSE 必需
#     proxy_read_timeout 300s;
#   }
# }
# nginx -t && nginx -s reload
# 云安全组放行 8843/TCP
# 访问: https://<你的域名>:8843/
NGINX
