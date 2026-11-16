PYTHON ?= .venv/bin/python
.DEFAULT_GOAL := help
.PHONY: help setup test check local-up local-down
help:
	@printf 'make setup      Create a local Python environment for offline tests\nmake test       Run application/platform unit tests (no cluster)\nmake check      Tests plus Python syntax checks (no cluster)\nmake local-up   Explicit Docker Compose build/start (local only)\nmake local-down Stop Compose; preserve its data volume\n'
setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements-test.txt
test:
	$(PYTHON) -m unittest discover -s tests -v
check: test
	$(PYTHON) -m compileall -q apps scripts tests
	sh -n deploy/build.sh
local-up:
	docker compose up --build -d
local-down:
	docker compose down
