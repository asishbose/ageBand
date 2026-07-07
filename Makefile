# ── Configuration ─────────────────────────────────────────────────────────────
IMAGE_NAME       := ageband-agent
UI_IMAGE_NAME    := ageband-ui
IMAGEREPO        ?=
VERSION          ?= latest
HELM_CHART_PATH  := helm/ageband
HELM_RELEASE     := ageband

PYTHON      := python3
PIP         := pip3
NPM         := npm
UI_DIR      := src/ui
PYTEST_ARGS := --cov=src --cov-report=term-missing

# Local dev defaults — override via `.env` or `export` before `make run`
LOCAL_API_BASE ?= http://localhost:8000/v1
LOCAL_MODEL    ?= Qwen/Qwen2.5-7B-Instruct
LOCAL_API_KEY  ?= EMPTY

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  := \033[32m
BLUE   := \033[34m
YELLOW := \033[33m
RED    := \033[31m
RESET  := \033[0m

# ── Default target ────────────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@echo "$(BLUE)AgeBand Build System$(RESET)"
	@echo ""
	@echo "$(YELLOW)Common:$(RESET)"
	@echo "  make setup                 # Install Python + UI deps, create .env"
	@echo "  make run                   # Start the agent service (reload)"
	@echo "  make run-ui                # Start the UI dev server"
	@echo "  make test                  # Run the full test suite"
	@echo "  make quality                # Lint + typecheck + complexity gates"
	@echo "  make eval-synthetic        # Generate fixtures + run eval harness"
	@echo ""
	@awk 'BEGIN {FS=":.*##"} /^[a-zA-Z_-]+:.*?##/ \
		{printf "  $(GREEN)%-24s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Environment ───────────────────────────────────────────────────────────────
.PHONY: setup-env
setup-env: ## Create .env from .env.example (if not already present)
	@test -f .env && echo "$(YELLOW).env already exists – skipping$(RESET)" || \
		{ cp .env.example .env; echo "$(GREEN)✓ .env created – update it with your config$(RESET)"; }

# ── Install ───────────────────────────────────────────────────────────────────
.PHONY: install
install: ## Install Python runtime + dev dependencies
	$(PIP) install -r requirements.txt

.PHONY: install-ui
install-ui: ## Install UI (npm) dependencies
	cd $(UI_DIR) && $(NPM) install

.PHONY: setup
setup: install install-ui setup-env ## Full local setup: Python deps, UI deps, .env
	@echo "$(GREEN)✓ Setup complete$(RESET)"

# ── Development ───────────────────────────────────────────────────────────────
.PHONY: run
run: ## Run the agent service locally (reload, AMD check skipped)
	SKIP_AMD_CHECK=true \
	LOCAL_API_BASE=$(LOCAL_API_BASE) \
	LOCAL_MODEL=$(LOCAL_MODEL) \
	LOCAL_API_KEY=$(LOCAL_API_KEY) \
	uvicorn src.orchestration.api:app --host 0.0.0.0 --port 8080 --reload

.PHONY: run-ui
run-ui: ## Run the UI dev server (proxies /v1/ to localhost:8080)
	cd $(UI_DIR) && $(NPM) run dev

.PHONY: health
health: ## Check local agent service health
	@curl -sf http://localhost:8080/health \
		&& echo "$(GREEN)✓ Service healthy$(RESET)" \
		|| echo "$(RED)✗ Service not responding$(RESET)"

# ── Tests ─────────────────────────────────────────────────────────────────────
.PHONY: test
test: ## Run the full test suite with coverage
	pytest tests/ $(PYTEST_ARGS)

.PHONY: test-unit
test-unit: ## Run unit tests only (fast, mocked LLM)
	pytest tests/unit/ -v

.PHONY: test-integration
test-integration: ## Run integration tests only
	pytest tests/integration/ -v

.PHONY: test-e2e
test-e2e: ## Run end-to-end scenario tests (adversarial, fairness, happy-path)
	pytest tests/e2e/ -v

.PHONY: test-ui
test-ui: ## Run UI tests (vitest)
	cd $(UI_DIR) && $(NPM) run test

.PHONY: coverage-gate
coverage-gate: ## Enforce the ≥85% coverage quality gate
	pytest tests/ --cov=src --cov-fail-under=85

# ── Quality gates ─────────────────────────────────────────────────────────────
.PHONY: lint
lint: ## Run ruff
	ruff check src/

.PHONY: lint-ui
lint-ui: ## Run eslint on the UI
	cd $(UI_DIR) && $(NPM) run lint

.PHONY: format
format: ## Auto-format with black + ruff --fix
	black src/ tests/
	ruff check src/ --fix

.PHONY: typecheck
typecheck: ## Run mypy --strict
	mypy src/ --strict --ignore-missing-imports

.PHONY: complexity
complexity: ## Check Radon cyclomatic complexity + maintainability index
	@echo "$(BLUE)Radon complexity check…$(RESET)"
	radon cc src/ -n B
	radon mi src/ -n B
	@echo "$(GREEN)✓ Complexity check passed$(RESET)"

.PHONY: quality
quality: lint typecheck complexity coverage-gate ## Run all quality gates (lint + typecheck + complexity + coverage)
	@echo "$(GREEN)✓ All quality gates passed$(RESET)"

# ── Docker ────────────────────────────────────────────────────────────────────
.PHONY: docker
docker: ## Build the agent Docker image locally (tags :VERSION and :latest)
	@echo "$(BLUE)Building $(IMAGE_NAME):$(VERSION)…$(RESET)"
	docker build -t $(IMAGE_NAME):$(VERSION) -t $(IMAGE_NAME):latest .
	@echo "$(GREEN)✓ Built $(IMAGE_NAME):$(VERSION)$(RESET)"

.PHONY: docker-ui
docker-ui: ## Build the UI Docker image locally (tags :VERSION and :latest)
	@echo "$(BLUE)Building $(UI_IMAGE_NAME):$(VERSION)…$(RESET)"
	docker build -f $(UI_DIR)/Dockerfile.ui -t $(UI_IMAGE_NAME):$(VERSION) -t $(UI_IMAGE_NAME):latest $(UI_DIR)/
	@echo "$(GREEN)✓ Built $(UI_IMAGE_NAME):$(VERSION)$(RESET)"

.PHONY: docker-build-all
docker-build-all: docker docker-ui ## Build both agent and UI images

.PHONY: _require-imagerepo
_require-imagerepo:
	@test -n "$(IMAGEREPO)" || \
		{ echo "$(RED)Error: IMAGEREPO is required  →  make docker-push IMAGEREPO=myregistry:5000$(RESET)"; exit 1; }

.PHONY: docker-push
docker-push: _require-imagerepo docker ## Tag + push the agent image to IMAGEREPO
	docker tag $(IMAGE_NAME):$(VERSION) $(IMAGEREPO)/$(IMAGE_NAME):$(VERSION)
	docker tag $(IMAGE_NAME):$(VERSION) $(IMAGEREPO)/$(IMAGE_NAME):latest
	docker push $(IMAGEREPO)/$(IMAGE_NAME):$(VERSION)
	docker push $(IMAGEREPO)/$(IMAGE_NAME):latest
	@echo "$(GREEN)✓ Pushed $(IMAGEREPO)/$(IMAGE_NAME):$(VERSION)$(RESET)"

.PHONY: docker-push-ui
docker-push-ui: _require-imagerepo docker-ui ## Tag + push the UI image to IMAGEREPO
	docker tag $(UI_IMAGE_NAME):$(VERSION) $(IMAGEREPO)/$(UI_IMAGE_NAME):$(VERSION)
	docker tag $(UI_IMAGE_NAME):$(VERSION) $(IMAGEREPO)/$(UI_IMAGE_NAME):latest
	docker push $(IMAGEREPO)/$(UI_IMAGE_NAME):$(VERSION)
	docker push $(IMAGEREPO)/$(UI_IMAGE_NAME):latest
	@echo "$(GREEN)✓ Pushed $(IMAGEREPO)/$(UI_IMAGE_NAME):$(VERSION)$(RESET)"

.PHONY: docker-push-all
docker-push-all: docker-push docker-push-ui ## Tag + push both agent and UI images to IMAGEREPO
	@echo "$(GREEN)✓ Pushed both images at $(VERSION)$(RESET)"

.PHONY: docker-run
docker-run: ## Run the agent container locally
	docker run --rm -it \
		-p 8080:8080 \
		-e LOCAL_API_BASE=$(LOCAL_API_BASE) \
		-e LOCAL_MODEL=$(LOCAL_MODEL) \
		-e SKIP_AMD_CHECK=true \
		--name ageband-agent \
		$(IMAGE_NAME):latest

.PHONY: docker-run-ui
docker-run-ui: ## Run the UI container locally (nginx, port 8081)
	docker run --rm -it \
		-p 8081:80 \
		--name ageband-ui \
		$(UI_IMAGE_NAME):latest

.PHONY: docker-stop
docker-stop: ## Stop the locally running agent + UI containers
	docker stop ageband-agent 2>/dev/null || true
	docker stop ageband-ui 2>/dev/null || true

# ── Helm ──────────────────────────────────────────────────────────────────────
.PHONY: helm-lint
helm-lint: ## Lint the Helm chart
	helm lint $(HELM_CHART_PATH)

.PHONY: helm-install-local
helm-install-local: ## Install/upgrade the chart (agent + UI) into the current kubectl context
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART_PATH) \
		--set agent.env.LOCAL_API_BASE=$(LOCAL_API_BASE) \
		--set agent.env.LOCAL_MODEL=$(LOCAL_MODEL) \
		--wait

.PHONY: helm-release
helm-release: _require-imagerepo docker-push-all ## Push agent+UI images to IMAGEREPO, then install the chart pointed at them
	@echo "$(BLUE)Deploying $(HELM_RELEASE) with images at $(IMAGEREPO):$(VERSION)…$(RESET)"
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART_PATH) \
		--set agent.image.repository=$(IMAGEREPO)/$(IMAGE_NAME) \
		--set agent.image.tag=$(VERSION) \
		--set ui.image.repository=$(IMAGEREPO)/$(UI_IMAGE_NAME) \
		--set ui.image.tag=$(VERSION) \
		--set agent.env.LOCAL_API_BASE=$(LOCAL_API_BASE) \
		--set agent.env.LOCAL_MODEL=$(LOCAL_MODEL) \
		--wait
	@echo "$(GREEN)✓ Deployed $(HELM_RELEASE) (agent + UI) at $(VERSION)$(RESET)"

.PHONY: helm-uninstall
helm-uninstall: ## Uninstall the chart from the current context
	helm uninstall $(HELM_RELEASE)

# ── Synthetic evaluation ───────────────────────────────────────────────────────
# Env vars required for LLM-backed runs (see docs/modules/synthetic_eval.md):
#   GENERATOR_API_BASE, GENERATOR_MODEL, GENERATOR_API_KEY
#   EVAL_API_BASE, EVAL_MODEL, EVAL_API_KEY
SYNTHETIC_DIR := tests/fixtures/synthetic
EVAL_N        ?= 20

.PHONY: eval-synthetic
eval-synthetic: ## Generate fixtures (if absent) then run the eval harness
	@if [ -z "$$(ls -A $(SYNTHETIC_DIR) 2>/dev/null)" ]; then \
		$(PYTHON) scripts/generate_synthetic_chats.py --all --count $(EVAL_N); \
	fi
	$(PYTHON) scripts/eval_pipeline_against_synthetic.py

.PHONY: eval-clean
eval-clean: ## Remove generated synthetic fixtures and eval result reports
	rm -rf $(SYNTHETIC_DIR) scripts/eval_results/
	@echo "$(GREEN)✓ Synthetic fixtures and eval results removed$(RESET)"

# ── Clean ─────────────────────────────────────────────────────────────────────
.PHONY: clean
clean: ## Remove build artefacts and caches (Python + coverage)
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete
	find . -type f -name "*.log" -delete

.PHONY: clean-ui
clean-ui: ## Remove UI build artefacts (dist/, node_modules/)
	rm -rf $(UI_DIR)/dist $(UI_DIR)/node_modules

.PHONY: clean-all
clean-all: clean clean-ui ## Remove everything including virtual envs and UI deps
	rm -rf venv/ .venv/
