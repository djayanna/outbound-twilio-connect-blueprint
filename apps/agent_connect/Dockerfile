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
COPY apps/agent_connect/ apps/agent_connect/
RUN uv sync --package agent-connect --no-dev

EXPOSE 3002
CMD ["uv", "run", "--package", "agent-connect", "uvicorn", "agent_connect.main:app", "--host", "0.0.0.0", "--port", "3002"]
