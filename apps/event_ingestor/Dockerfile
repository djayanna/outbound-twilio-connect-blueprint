FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY apps/scheduler/pyproject.toml apps/scheduler/pyproject.toml
COPY apps/agent_connect/pyproject.toml apps/agent_connect/pyproject.toml
COPY apps/event_ingestor/pyproject.toml apps/event_ingestor/pyproject.toml

COPY shared/ shared/
COPY apps/event_ingestor/ apps/event_ingestor/
RUN uv sync --package event-ingestor --no-dev

EXPOSE 3003
CMD ["uv", "run", "--package", "event-ingestor", "uvicorn", "event_ingestor.main:app", "--host", "0.0.0.0", "--port", "3003"]
