# Research Agent System

A production-grade multi-agent research system demonstrating senior-level AI engineering patterns:
agent orchestration, MCP protocol abstraction, graceful degradation, streaming responses, and distributed tracing.

```text
┌─────────────────┐
│  Orchestrator   │  ReWOO planner + smolagents
│   Agent Core    │
└────────┬────────┘
         │
    ┌────┴────┐
    │   MCP   │  Protocol abstraction layer
    │ Gateway │  (dynamic routing + fallback chains)
    └────┬────┘
         │
    ┌────┴───────────────────┐
    │                        │
┌───▼────┐            ┌─────▼──────┐
│ Search │            │ Summarize  │
│  MCP   │            │    MCP     │
│ Server │            │   Server   │
└────────┘            └────────────┘
    │                       │
[Tavily API]          [Claude API]

Observable via Phoenix (trace spans)
```

## Architecture Decisions

### Why MCP?

MCP (Model Context Protocol) gives us a **clean abstraction boundary** between agent logic and tool implementation.
Each MCP server is independently deployable, replaceable, and testable. The orchestrator never knows
whether Search is backed by Tavily or a scraper — it just calls the tool.

### Why ReWOO-style planning?

ReWOO (Reason → Plan → Execute) separates the planning phase from execution. This means:

- All tool calls can be audited before execution
- Parallel planning is possible (Phase 2 extension)
- Easier to instrument with Phoenix spans

### Graceful Degradation

- Search MCP: Tavily fails → falls back to scraper (no API key needed)
- Summarization MCP: returns degraded message instead of crashing
- Orchestrator: if summarization unavailable → uses its own LLM pass

### Trade-offs (Intentional Simplifications)

| Simplified | Why | Extension Path |
|------------|-----|----------------|
| No multi-turn memory | Keeps state trivial | Add Cloud SQL sessions |
| Synchronous MCP calls | Easier to debug | Add asyncio.gather() once stable |
| No circuit breakers | Reduce initial complexity | Add after load testing |

---

## Quick Start

```bash
# 1. Setup — installs uv, deps, pre-commit hooks, creates .env
make init

# 2. Add your API keys to .env
vim .env

# 3. Build and start all services
make build
make up

# 4. Check all services are healthy
make health

# 5. Run a research query
make query Q="What is Model Context Protocol and why does it matter?"

# 6. Run a streaming query
make query-stream Q="Latest AI agent frameworks 2025"
```

---

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| Orchestrator | http://localhost:8000 | Main API + agent loop |
| Search MCP | http://localhost:8001 | Web search tool server |
| Summarization MCP | http://localhost:8002 | Text synthesis tool server |
| Phoenix UI | http://localhost:6006 | Distributed tracing + spans |
| Redis | localhost:6379 | Search result cache |
| PostgreSQL | localhost:5432 | Query history |

---

## Make Commands

```bash
# ── Setup ─────────────────────────────────────────────────────────────────────
make init                  # bootstrap project (uv, deps, pre-commit, .env)

# ── Docker ────────────────────────────────────────────────────────────────────
make build                 # build all service images
make up                    # start all services
make down                  # stop all services
make down-volumes          # stop and remove volumes (DESTRUCTIVE)
make restart               # restart all services
make update                # pull latest base images and restart
make logs                  # tail all logs
make logs SERVICE=search-mcp  # tail logs for a specific service
make docker-prune          # remove unused Docker resources

# ── Queries ───────────────────────────────────────────────────────────────────
make query Q="your question"         # run a research query
make query-stream Q="your question"  # run a streaming research query

# ── Health & Observability ────────────────────────────────────────────────────
make health                # check health of all services
make phoenix               # open Phoenix tracing UI in browser

# ── Database ──────────────────────────────────────────────────────────────────
make db-shell              # open psql shell on Postgres
make db-history            # show last 10 research queries

# ── Cache ─────────────────────────────────────────────────────────────────────
make cache-flush           # flush all Redis search cache entries
make cache-stats           # show Redis memory usage and key count

# ── Dev ───────────────────────────────────────────────────────────────────────
make lint                  # run ruff linter
make format                # run ruff formatter
```

---

## Observability

Open Phoenix at http://localhost:6006 to see:

- Agent reasoning loop spans
- MCP server call latencies
- Tool selection frequency
- Planning vs execution time ratio

---

## Build Phases

- [x] **Phase 1** – Project scaffold, MCP servers (Search + Summarization)
- [ ] **Phase 2** – Orchestrator agent (ReWOO planner + MCP gateway + streaming)
- [ ] **Phase 3** – Phoenix observability integration
- [ ] **Phase 4** – GCP deployment (Cloud Run + Terraform)
- [ ] **Phase 5** – Portfolio polish (load tests, architecture diagrams)