#!/bin/sh
set -eu

SENTINEL="token-log-sentinel-$$"
NETWORK="ai-interview-token-log-$SENTINEL"
BACKEND="ai-interview-token-backend-$SENTINEL"
NGINX="ai-interview-token-nginx-$SENTINEL"
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
  ROOT_DIR="$(cygpath -w "$ROOT_DIR")"
fi

cleanup() {
  docker rm -f "$NGINX" "$BACKEND" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker network create "$NETWORK" >/dev/null
docker run -d --name "$BACKEND" --network "$NETWORK" \
  --network-alias backend busybox:1.36 \
  httpd -f -p 8000 >/dev/null
MSYS_NO_PATHCONV=1 docker run -d --name "$NGINX" --network "$NETWORK" \
  -v "$ROOT_DIR/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.27-alpine >/dev/null

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if docker exec "$NGINX" wget -q -O /dev/null http://127.0.0.1/; then
    break
  fi
  if [ "$attempt" -eq 10 ]; then
    echo "Nginx 日志验证容器未就绪" >&2
    exit 1
  fi
  sleep 1
done

for path in \
  "/public/coding-tests/$SENTINEL-coding" \
  "/offer-confirm/$SENTINEL-offer" \
  "/public/review/$SENTINEL-review" \
  "/api/public/coding-tests/$SENTINEL-coding" \
  "/api/public/offers/confirm/$SENTINEL-offer" \
  "/api/public/review/$SENTINEL-review"
do
  docker exec "$NGINX" wget -q -O /dev/null "http://127.0.0.1$path" || true
done

# 制造真实上游失败，验证 error log 也不会携带 API token。
docker rm -f "$BACKEND" >/dev/null
docker exec "$NGINX" wget -q -O /dev/null \
  "http://127.0.0.1/api/public/review/$SENTINEL-review-upstream-failure" || true

LOGS="$(docker logs "$NGINX" 2>&1 || true)"
FILES="$(docker exec "$NGINX" sh -c \
  'for file in /var/log/nginx/access.log /var/log/nginx/error.log; do
     if [ -f "$file" ] && [ ! -L "$file" ]; then cat "$file"; fi
   done' 2>/dev/null || true)"
if printf '%s\n%s\n' "$LOGS" "$FILES" | grep -F "$SENTINEL" >/dev/null; then
  echo "Nginx 日志泄漏了公开令牌哨兵" >&2
  exit 1
fi

echo "Nginx 公开令牌日志验证通过"
