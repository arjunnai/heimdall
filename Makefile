.PHONY: install seed run api mcp eval eval-fixture demo test lint verify

PYTHON ?= .venv/bin/python

install:
	uv venv --python 3.11
	uv pip install --python .venv/bin/python -r requirements-dev.txt

seed:
	$(PYTHON) db/seed.py $(or $(SEED),checkout_v42_pool)

run: api

api:
	$(PYTHON) -m uvicorn app.main:app --reload

mcp:
	$(PYTHON) -m app.tools.mcp_server

eval:
	$(PYTHON) -m evals.eval --backend $${EVAL_BACKEND:-postgres}

eval-fixture:
	$(PYTHON) -m evals.eval --backend fixture

demo:
	$(PYTHON) -m app.cli --seed checkout_v42_pool \
	  "Checkout p95 rose to 1.8s after v42; pool timeouts are firing."

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check app db evals tests ui

verify: lint test eval-fixture
