.PHONY: help install dev test lint fmt run docker-build docker-up docker-down clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	pip install -r requirements.txt

dev:  ## Install dev dependencies
	pip install -e ".[dev]"

test:  ## Run tests
	python -m pytest tests/ -v --tb=short

test-cov:  ## Run tests with coverage
	python -m pytest tests/ -v --cov=gateway --cov-report=term-missing --cov-report=html

lint:  ## Run linter
	ruff check gateway/ tests/

fmt:  ## Format code
	ruff format gateway/ tests/

run:  ## Run development server
	uvicorn gateway.api:app --host 0.0.0.0 --port 8900 --reload

run-legacy:  ## Run legacy single-file server
	python gateway.py

docker-build:  ## Build Docker image
	docker compose build

docker-up:  ## Start services
	docker compose up -d

docker-down:  ## Stop services
	docker compose down

docker-logs:  ## View logs
	docker compose logs -f gateway

clean:  ## Clean caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage *.egg-info/
