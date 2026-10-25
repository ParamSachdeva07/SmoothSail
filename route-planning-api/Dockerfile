FROM python:3.13-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" DATA_DIR=/app/data \
    TIDELINE_MODE=mongo AUTO_REFRESH_FORECASTS=false
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra providers --no-install-project
COPY service ./service
COPY scripts/__init__.py scripts/ingest_compliance.py ./scripts/
COPY data/planning ./data/planning
COPY data/portwatch_mappings.json ./data/portwatch_mappings.json
RUN useradd --uid 10001 --create-home app && mkdir -p /app/data/cache && chown -R app:app /app/data
USER app
EXPOSE 8080
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--timeout-graceful-shutdown", "600"]
