# Consensus: FastAPI + MCP server, optionally serving the built frontend from the
# same origin. Needs PostgreSQL (pgvector) and Redis via DATABASE_URL / REDIS_URL.
# See docs/deploy.md.

# ---- stage 1: build the frontend if the repo has one (main may not; Frontend does)
FROM node:22-alpine AS frontend
WORKDIR /src
COPY . .
RUN mkdir -p /out && \
    if [ -f frontend/package.json ]; then \
      cd frontend && npm ci --no-audit --no-fund && npm run build && cp -r dist/. /out/; \
    else echo "no frontend/ in this build; API only"; fi

# ---- stage 2: the app
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY docker/entrypoint.sh ./docker/entrypoint.sh
# Built frontend (empty directory when the source tree had none). Served at / when index.html exists.
COPY --from=frontend /out ./frontend/dist
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh \
    && useradd --create-home --uid 10001 consensus && chown -R consensus:consensus /app
USER consensus

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker/entrypoint.sh"]
