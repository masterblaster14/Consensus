#!/bin/sh
# Container entrypoint: migrate, optionally seed, serve.
#   PORT        port to listen on (Render / Railway set this; default 8000)
#   SEED_DEMO   "true" to load the demo organisation, project and memory on boot (idempotent)
set -e

echo "consensus: applying migrations"
n=0
until python -m alembic upgrade head; do
  n=$((n + 1))
  if [ "$n" -ge 12 ]; then
    echo "consensus: database not reachable after $n attempts" >&2
    exit 1
  fi
  echo "consensus: database not ready, retrying ($n)"
  sleep 5
done

if [ "${SEED_DEMO:-false}" = "true" ]; then
  echo "consensus: seeding demo data"
  python -m scripts.seed_demo || echo "consensus: seed failed (continuing)" >&2
fi

exec python -m uvicorn app.main:app \
  --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*"
