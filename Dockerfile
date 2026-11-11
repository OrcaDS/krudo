# Pipeline image: ingestion, dbt, publish. Secrets come from env vars at runtime, never baked in.

# --- builder: resolve and install locked dependencies with uv ---
FROM python:3.12.10-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, so code changes don't invalidate the dependency layer
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY config ./config
COPY ingestion ./ingestion
COPY pipeline ./pipeline
RUN uv sync --locked --no-dev --no-editable

# --- runtime: slim image, non-root, only the virtualenv and code ---
FROM python:3.12.10-slim-bookworm AS runtime
RUN useradd --create-home --uid 10001 pipeline
WORKDIR /app
COPY --from=builder --chown=pipeline:pipeline /app/.venv /app/.venv
COPY transform ./transform
# dbt's own scratch dirs: keep them out of the (read-only) project dir
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    DBT_TARGET_PATH=/tmp/dbt/target DBT_LOG_PATH=/tmp/dbt/logs
# The default LAKE_ROOT (./lake, also in .env.example) resolves here; mount a volume on it
RUN mkdir /app/lake && chown pipeline:pipeline /app/lake
USER pipeline
ENTRYPOINT ["krudo"]
CMD ["--help"]
