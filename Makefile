.PHONY: setup test bootstrap api mcp bench

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest -q

bootstrap:
	.venv/bin/python scripts/bootstrap.py

api:
	.venv/bin/uvicorn app.main:app --reload --port 8080

mcp:
	.venv/bin/python -m app.mcp_server.server

bench:
	.venv/bin/python scripts/run_benchmark.py --limit 3
