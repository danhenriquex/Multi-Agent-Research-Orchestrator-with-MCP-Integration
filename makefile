PROJECT_NAME := research-agent
COMPOSE_FILE := docker-compose.yml
ENV_FILE     := .env

COMPOSE_CMD = docker compose -p $(PROJECT_NAME) -f $(COMPOSE_FILE) --env-file $(ENV_FILE)

# Default query for 'make query'
Q ?= What is Model Context Protocol and why does it matter for AI agents?

######### Help #########
.PHONY: help
help: ## Show all available targets
	@echo "Usage: make [target] [ARGS]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {sub("\\\\n",sprintf("\n%22c"," "), $$2); printf "  \033[36m%-20s\033[0m  %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Examples:"
	@echo '  make query Q="Latest AI agent frameworks 2024"'
	@echo "  make logs SERVICE=search-mcp"

######### Setup #########
.PHONY: init
init: ## Bootstrap the project (install uv, deps, pre-commit, create .env)
	./scripts/init.sh

######### Docker Compose #########
.PHONY: up down down-volumes restart build update logs docker-prune rebuild rebuild-clean

up: ## Start all services in detached mode (2 min timeout)
	$(COMPOSE_CMD) up -d --wait --wait-timeout 120

down: ## Stop all services
	$(COMPOSE_CMD) down

down-volumes: ## Stop all services and remove volumes (DESTRUCTIVE: clears DB + cache)
	$(COMPOSE_CMD) down --volumes

restart: ## Restart all services
	$(COMPOSE_CMD) down && $(COMPOSE_CMD) up -d

build: ## Build all service images
	$(COMPOSE_CMD) build

update: ## Pull latest base images and restart
	$(COMPOSE_CMD) pull && $(COMPOSE_CMD) up -d

logs: ## Tail logs for all services (or specific: make logs SERVICE=search-mcp)
ifdef SERVICE
	$(COMPOSE_CMD) logs -f $(SERVICE)
else
	$(COMPOSE_CMD) logs -f
endif

rebuild: ## Rebuild and restart one service (usage: make rebuild s=search-agent)
	$(COMPOSE_CMD) up -d --build $(s)

rebuild-clean: ## Force rebuild with no cache (usage: make rebuild-clean s=search-agent)
	$(COMPOSE_CMD) build --no-cache $(s) && $(COMPOSE_CMD) up -d $(s)

docker-prune: ## Remove unused Docker containers, images and volumes
	docker system prune -a --volumes -f

######### Health & Observability #########
.PHONY: health phoenix phoenix-start phoenix-logs status debug

health: ## Check health of all running services
	@echo "\n=== Service Health ==="
	@curl -sf http://localhost:8001/mcp > /dev/null && echo "✓ search-mcp (port 8001)" || echo "✗ search-mcp (not running?)"
	@curl -sf http://localhost:8002/mcp > /dev/null && echo "✓ summarization-mcp (port 8002)" || echo "✗ summarization-mcp (not running?)"
	@curl -sf http://localhost:8000/health | python3 -m json.tool && echo "✓ orchestrator" || echo "✗ orchestrator (not running?)"
	@echo ""

phoenix-start: ## Start Phoenix container if not running
	$(COMPOSE_CMD) up -d phoenix
	@echo "Phoenix starting at http://localhost:6006 (may take a few seconds)"

phoenix-logs: ## Tail Phoenix logs
	$(COMPOSE_CMD) logs -f phoenix

status: ## Show status of all containers
	$(COMPOSE_CMD) ps

debug: ## Show logs for phoenix and orchestrator (most common failure points)
	@echo "\n=== Phoenix logs ==="
	$(COMPOSE_CMD) logs --tail=30 phoenix
	@echo "\n=== Orchestrator logs ==="
	$(COMPOSE_CMD) logs --tail=30 orchestrator

phoenix: ## Start Phoenix and open UI in browser
	$(COMPOSE_CMD) up -d phoenix
	@sleep 3
	@echo "Opening Phoenix at http://localhost:6006"
	@open http://localhost:6006 2>/dev/null || xdg-open http://localhost:6006 2>/dev/null || echo "Visit: http://localhost:6006"

######### Research Queries #########
.PHONY: query query-stream

query: ## Run a research query (usage: make query Q="your question")
	@echo "Query: $(Q)\n"
	@curl -sf -X POST http://localhost:8000/research \
		-H "Content-Type: application/json" \
		-d '{"query": "$(Q)"}' | python3 -m json.tool

query-stream: ## Run a streaming research query (usage: make query-stream Q="your question")
	@echo "Streaming query: $(Q)\n"
	@curl -N -X POST http://localhost:8000/research/stream \
		-H "Content-Type: application/json" \
		-d '{"query": "$(Q)"}'

######### Database #########
.PHONY: db-shell db-history

db-shell: ## Open a psql shell on the running Postgres container
	$(COMPOSE_CMD) exec postgres psql -U agent -d research_agent

db-history: ## Show last 10 research queries stored in Postgres
	$(COMPOSE_CMD) exec postgres psql -U agent -d research_agent \
		-c "SELECT id, left(query,60) AS query, status, duration_ms, created_at FROM research_queries ORDER BY created_at DESC LIMIT 10;"

######### Cache #########
.PHONY: cache-flush cache-stats

cache-flush: ## Flush all Redis search cache entries
	$(COMPOSE_CMD) exec redis redis-cli --scan --pattern "search:*" | xargs -r \
		$(COMPOSE_CMD) exec -T redis redis-cli DEL
	@echo "Search cache flushed"

cache-stats: ## Show Redis memory usage and key count
	@$(COMPOSE_CMD) exec redis redis-cli info memory | grep used_memory_human
	@echo "Search keys: $$($(COMPOSE_CMD) exec redis redis-cli --scan --pattern 'search:*' | wc -l)"

######### Tests #########
.PHONY: test test-cov test-integration

test: ## Run unit tests
	uv run pytest tests/unit/ -v --tb=short

test-cov: ## Run unit tests with coverage report
	uv run pytest tests/unit/ -v --tb=short --cov=src --cov-report=term-missing

test-integration: ## Run integration tests (requires: make up)
	uv run pytest tests/integration/ -v --tb=short

######### Evals #########
.PHONY: evals evals-dry evals-summary

evals: ## Run Phoenix LLM-as-a-judge evaluators (requires: make up + some queries)
	uv run python evals/phoenix_evals.py

evals-dry: ## Run evals in dry-run mode (no LLM calls — just counts spans)
	uv run python evals/phoenix_evals.py --dry-run

evals-summary: ## Run only summary clarity evaluator
	uv run python evals/phoenix_evals.py --only summary

######### Dev helpers #########
.PHONY: lint format

lint: ## Run ruff linter across all Python files
	uv run ruff check .

format: ## Run ruff formatter across all Python files
	uv run ruff format .

######### A2A targets #########
.PHONY: agents-health a2a-demo a2a-factcheck

agents-health: ## Health check all 3 A2A agents
	@echo "--- A2A Agent Health ---"
	@curl -s http://localhost:8010/health | python3 -m json.tool
	@curl -s http://localhost:8011/health | python3 -m json.tool
	@curl -s http://localhost:8012/health | python3 -m json.tool

a2a-demo: ## Call search agent directly via A2A
	@echo "--- Calling Search Agent directly via A2A ---"
	@curl -s -X POST http://localhost:8010/a2a \
	  -H "Content-Type: application/json" \
	  -d '{"sender":"demo","receiver":"search","task":"search","payload":{"query":"agent to agent protocol AI"}}' \
	  | python3 -m json.tool

a2a-factcheck: ## Call fact-check agent directly via A2A
	@echo "--- Calling Fact-Check Agent directly via A2A ---"
	@curl -s -X POST http://localhost:8012/a2a \
	  -H "Content-Type: application/json" \
	  -d '{"sender":"demo","receiver":"fact_check","task":"fact_check","payload":{"summary":"The sky is blue due to Rayleigh scattering.","query":"why is the sky blue"}}' \
	  | python3 -m json.tool
