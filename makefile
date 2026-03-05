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
.PHONY: up down down-volumes restart build update logs docker-prune

up: ## Start all services in detached mode
	$(COMPOSE_CMD) up -d

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

docker-prune: ## Remove unused Docker containers, images and volumes
	docker system prune -a --volumes -f

######### Health & Observability #########
.PHONY: health phoenix

health: ## Check health of all running services
	@echo "\n=== Service Health ==="
	@curl -sf http://localhost:8001/mcp > /dev/null && echo "✓ search-mcp (port 8001)" || echo "✗ search-mcp (not running?)"
	@curl -sf http://localhost:8002/mcp > /dev/null && echo "✓ summarization-mcp (port 8002)" || echo "✗ summarization-mcp (not running?)"
	@curl -sf http://localhost:8000/health | python3 -m json.tool && echo "✓ orchestrator" || echo "✗ orchestrator (not running?)"
	@echo ""

phoenix: ## Open Phoenix observability UI in browser
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

cache-flush: ## Flush all Redis cache entries (search cache only)
	$(COMPOSE_CMD) exec redis redis-cli --scan --pattern "search:*" | xargs -r \
		$(COMPOSE_CMD) exec -T redis redis-cli DEL
	@echo "Search cache flushed"

cache-stats: ## Show Redis memory usage and key count
	@$(COMPOSE_CMD) exec redis redis-cli info memory | grep used_memory_human
	@echo "Search keys: $$($(COMPOSE_CMD) exec redis redis-cli --scan --pattern 'search:*' | wc -l)"

######### Dev helpers #########
.PHONY: lint format

lint: ## Run ruff linter across all Python files
	uv run ruff check .

format: ## Run ruff formatter across all Python files
	uv run ruff format .