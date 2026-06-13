# Verified Documentation Harness — backend (FastAPI + the loop + subprocess sandbox).
# Render builds this and runs the SSE API. The SPA deploys separately (Vercel).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HARNESS_RUNS_DIR=/tmp/runs

WORKDIR /app

# Copy only what the build/runtime needs (keeps the image small; see .dockerignore).
COPY pyproject.toml ./
COPY src ./src
COPY examples ./examples

# http = FastAPI/uvicorn; workers = anthropic/openai (model swap); otel = Langfuse OTLP.
RUN pip install --upgrade pip && pip install ".[http,workers,otel]"

# Render injects $PORT; bind to it (default 8000 for local `docker run`).
EXPOSE 8000
CMD ["sh", "-c", "uvicorn harness.adapters.http:app --host 0.0.0.0 --port ${PORT:-8000}"]
