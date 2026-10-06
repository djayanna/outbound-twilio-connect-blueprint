.PHONY: dev up down build test lint provision

dev:
	honcho start

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

test:
	uv run --all-packages pytest --cov

lint:
	uv run ruff check apps shared scripts tests

provision:
	uv sync --group provision
	uv run python scripts/provision.py
