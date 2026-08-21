FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install "uv>=0.6.0,<0.7.0"

COPY pyproject.toml README.md uv.lock ./
COPY app ./app
COPY migrations ./migrations
COPY tests ./tests
COPY alembic_core.ini alembic_memory.ini ./
COPY scripts ./scripts
COPY docker/entrypoint.sh /entrypoint.sh

RUN uv pip install --system -e ".[dev]" \
    && sed -i 's/\r$//' /entrypoint.sh \
    && chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
