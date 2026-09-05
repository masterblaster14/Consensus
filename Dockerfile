# Consensus backend: FastAPI + MCP server. Needs PostgreSQL (pgvector) and Redis,
# supplied via DATABASE_URL and REDIS_URL. See docs/deploy.md.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so source edits do not bust the layer cache.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh \
    && useradd --create-home --uid 10001 consensus && chown -R consensus:consensus /app
USER consensus

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker/entrypoint.sh"]
