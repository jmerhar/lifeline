.PHONY: help install browser dev up down logs shell build test test-backend test-frontend \
        test-browser coverage lint openapi contract inspect check migrate revision \
        db-shell node-modules \
        lockfile clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*##|^##@' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} {printf "  \033[36mmake %-16s\033[0m %s\n", $$1, $$2}'

##@ Setup

install: ## Create the backend virtualenv and install the frontend packages
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install --quiet --upgrade pip
	backend/.venv/bin/pip install --quiet -e "backend[test]"
	cd frontend && npm install --no-fund --no-audit
	@echo "Installed. 'make browser' adds the browser the interactive login needs."

browser: ## Download the Chromium build Playwright drives
	backend/.venv/bin/python -m playwright install chromium

##@ Development

dev: ## Start the stack with hot reload (API on :8000, interface on :5173)
	bin/dev.sh

up: ## Build and start the production stack
	docker compose -f docker-compose.yml -f docker-compose.build.yml up --build -d
	@echo "Interface: http://127.0.0.1:8000 — the setup token is in 'make logs'."

down: ## Stop the stack, keeping the data
	docker compose down

logs: ## Follow the container's log (where the setup token is printed)
	docker compose logs -f

shell: ## Open a shell in the running container
	docker compose exec lifeline sh

build: ## Build the image without starting anything
	docker compose -f docker-compose.yml -f docker-compose.build.yml build

##@ Testing

test: test-backend test-frontend ## Run both test suites

test-backend: ## Run the backend suite (arguments pass through to pytest)
	bin/test-backend.sh $(ARGS)

test-frontend: ## Run the frontend suite
	bin/test-frontend.sh $(ARGS)

# Skipped unless a browser is installed and a display is available, so the ordinary suite
# needs neither. LIFELINE_TEST_DISPLAY names the display for the headful tests; on Linux
# start one with `Xvfb :99 &` and set it to :99.
test-browser: ## Run the tests that drive a real browser
	bin/test-backend.sh tests/test_integration -v

coverage: ## Run both suites with coverage and print the combined summary
	bin/coverage.sh --format md

lint: ## ShellCheck, TypeScript and ESLint
	bin/lint.sh

openapi: ## Re-export the API schema and regenerate the frontend's types
	bin/openapi.sh

contract: openapi ## Check the committed schema and generated types are up to date
	@git diff --exit-code frontend/openapi.json frontend/src/types/api.d.ts \
		|| { echo; echo "The schema changed. Commit the regenerated files above."; exit 1; }
	@echo "schema and types are current"

inspect: ## Run IntelliJ IDEA CLI inspections
	bin/inspect.sh

check: lint contract test coverage ## Everything (gate a commit on this)

##@ Database

migrate: ## Apply migrations to the development database
	bin/migrate.sh

revision: ## Generate a migration from the models (usage: make revision m="what changed")
	bin/migrate.sh revision --autogenerate -m "$(m)"

db-shell: ## Open a SQLite shell on the development database
	sqlite3 data/lifeline.db

##@ Housekeeping

node-modules: ## Reinstall the frontend packages
	cd frontend && rm -rf node_modules && npm install --no-fund --no-audit

lockfile: ## Regenerate package-lock.json (Linux binaries, public registry URLs)
	bin/lockfile.sh

clean: ## Remove build and coverage artefacts (all regenerable)
	rm -rf backend/htmlcov backend/coverage.xml backend/coverage.json backend/.coverage \
	       backend/junit frontend/coverage frontend/dist frontend/tsconfig.tsbuildinfo \
	       coverage-upload .coverage-report.py inspect
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
