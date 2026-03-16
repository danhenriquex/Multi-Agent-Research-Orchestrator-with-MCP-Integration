# Research Agent System

A production-grade multi-agent research system demonstrating senior-level AI engineering patterns:
A2A agent orchestration, MCP protocol abstraction, graceful degradation, streaming responses, and distributed tracing.

```text
┌─────────────────────┐
│  Supervisor Agent   │  ReWOO planner + A2A orchestration
│    (Orchestrator)   │
└─────────┬───────────┘
          │
     A2A Protocol (Agent ↔ Agent)
          │
┌─────────┼─────────────────────────┐
│         │                         │
┌─────────▼──────┐  ┌───────────────▼──┐  ┌──────────────────┐
│  Search Agent  │  │ Summarize Agent  │  │ Fact-Check Agent │
│    :8010       │  │    :8011         │  │    :8012  (NEW)  │
└────────┬───────┘  └────────┬─────────┘  └────────┬─────────┘
         │                   │                      │
    MCP Protocol        MCP Protocol           MCP Protocol
    (Agent ↔ Tool)     (Agent ↔ Tool)         (Agent ↔ Tool)
         │                   │                      │
┌────────▼───────┐  ┌────────▼─────────┐  ┌────────▼─────────┐
│   Search MCP   │  │ Summarization MCP│  │  Knowledge MCP   │
│    :8001       │  │    :8002         │  │    :8003  (NEW)  │
│  [Tavily API]  │  │  [OpenAI API]    │  │  [ChromaDB]      │
└────────────────┘  └──────────────────┘  └──────────────────┘

Observable via Phoenix (trace spans across all agents)
```

## Architecture Decisions

### Why A2A + MCP together?

**MCP (Model Context Protocol)** handles the vertical axis — agents calling tools.
Each MCP server is independently deployable and replaceable. The agent never knows whether
Search is backed by Tavily or a scraper — it just calls the tool.

**A2A (Agent-to-Agent)** handles the horizontal axis — agents collaborating with each other.
The Supervisor never calls MCP servers directly. It delegates to specialist agents via HTTP,
each of which privately manages its own MCP connections. This means agents can be scaled,
replaced, or upgraded without touching the orchestrator.

```
MCP  = vertical  (agent → tool)    one-directional, tool executes
A2A  = horizontal (agent ↔ agent)  bidirectional, agent reasons
```

### Why ReWOO-style planning?

ReWOO (Reason → Plan → Execute) separates the planning phase from execution:

- Full plan is auditable before any tool call runs
- Planning time vs execution time is separately measurable in Phoenix
- Easier to instrument with OpenTelemetry spans

### Fact-Check Agent & Self-Healing Loop

After every research cycle the Supervisor calls the Fact-Check Agent, which:
1. Searches ChromaDB for semantically similar content
2. Returns a confidence score (0.0–1.0) based on cosine similarity
3. If confidence < 0.50, the Supervisor automatically triggers a second search pass

This creates a self-healing loop without any hardcoded retry logic.

### Graceful Degradation

- **Search MCP**: Tavily fails → falls back to HTML scraper (no key needed)
- **Summarization MCP**: returns degraded message instead of crashing
- **Fact-Check Agent**: ChromaDB unavailable → returns `verified: null` (not `false`)
- **Orchestrator**: any agent down → logs warning, continues with partial results

### Trade-offs (Intentional Simplifications)

| Simplified | Why | Production Path |
|---|---|---|
| Direct HTTP for A2A | Simpler than message queue | RabbitMQ for async, fault tolerance |
| Static agent registry | No infrastructure needed | Consul / etcd for dynamic discovery |
| Full context in A2A messages | Stateless agents, easier to debug | Redis context store + context IDs |
| Fail-fast error handling | Weekend scope | Circuit breakers + partial results |

---

## Quick Start

```bash
# 1. Setup — installs uv, deps, pre-commit hooks, creates .env
make init

# 2. Add your API keys to .env
#    OPENAI_API_KEY=sk-...
#    TAVILY_API_KEY=tvly-...
vim .env

# 3. Build and start all services
make up

# 4. Check all services are healthy
make status
make health

# 5. Run a research query
make query Q="What is the A2A protocol for AI agents?"

# 6. Watch the streaming version (shows each agent hop in real time)
make query-stream Q="What is the A2A protocol for AI agents?"

# 7. Test A2A layer directly (bypasses orchestrator)
make a2a-demo

# 8. Open Phoenix to see distributed traces
make phoenix
```

---

## Services

| Service | URL | Purpose |
|---|---|---|
| Orchestrator | http://localhost:8000 | Supervisor agent + API |
| Search Agent | http://localhost:8010 | A2A agent → Search MCP |
| Summarize Agent | http://localhost:8011 | A2A agent → Summarization MCP |
| Fact-Check Agent | http://localhost:8012 | A2A agent → Knowledge MCP (NEW) |
| Search MCP | http://localhost:8001 | Tavily web search tool server |
| Summarization MCP | http://localhost:8002 | OpenAI synthesis tool server |
| Knowledge MCP | http://localhost:8003 | ChromaDB vector search (NEW) |
| Phoenix UI | http://localhost:6006 | Distributed tracing + spans |
| ChromaDB | http://localhost:8100 | Vector knowledge base (NEW) |
| Redis | localhost:6379 | Search result cache |
| PostgreSQL | localhost:5432 | Query history |

---

## Make Commands

```bash
# ── Setup ─────────────────────────────────────────────────────────────────────
make init                        # bootstrap project (uv, deps, pre-commit, .env)

# ── Docker ────────────────────────────────────────────────────────────────────
make up                          # start all services (2 min timeout)
make down                        # stop all services
make down-volumes                # stop and remove volumes (DESTRUCTIVE)
make restart                     # restart all services
make status                      # show status of all containers
make rebuild s=search-agent      # rebuild and restart one service
make rebuild-clean s=search-agent  # force rebuild with no cache

# ── Queries ───────────────────────────────────────────────────────────────────
make query Q="your question"         # run a full research query
make query-stream Q="your question"  # stream agent steps in real time

# ── A2A Testing ───────────────────────────────────────────────────────────────
make a2a-demo                    # call search agent directly via A2A
make a2a-factcheck               # call fact-check agent directly via A2A
make agents-health               # health check all 3 A2A agents

# ── Health & Observability ────────────────────────────────────────────────────
make health                      # check health of orchestrator + MCP servers
make phoenix                     # open Phoenix tracing UI in browser
make debug                       # show logs for phoenix and orchestrator

# ── Database ──────────────────────────────────────────────────────────────────
make db-shell                    # open psql shell on Postgres
make db-history                  # show last 10 research queries

# ── Cache ─────────────────────────────────────────────────────────────────────
make cache-flush                 # flush all Redis search cache entries
make cache-stats                 # show Redis memory usage and key count

# ── Tests ─────────────────────────────────────────────────────────────────────
make test                        # run unit tests
make test-cov                    # run unit tests with coverage report
make test-integration            # run integration tests (requires: make up)

# ── Dev ───────────────────────────────────────────────────────────────────────
make lint                        # run ruff linter
make format                      # run ruff formatter
make docker-prune                # remove unused Docker resources
```

---

## Observability

Open Phoenix at http://localhost:6006 after running a query. Each span shows:

- **Search Agent**: `input.query`, `output.num_results`, `output.backend`, top 3 result titles + URLs
- **Summarize Agent**: `input.source_urls`, `output.summary_preview` (first 500 chars), `output.input_tokens`
- **Fact-Check Agent**: `input.summary_preview`, `output.confidence`, `output.verified`, `output.flags`
- **Orchestrator**: end-to-end `duration_ms`, total `num_sources`

---

## Testing

```bash
# Unit tests (no stack required — all mocked)
make test

# Integration tests (requires full stack)
make up
make test-integration
```

**Unit tests** cover: A2A models, client routing, router dispatch, SupervisorAgent happy path,
fact-check failure graceful degradation, low-confidence recheck loop, protocol labeling.

**Integration tests** cover: all agent health endpoints, each A2A endpoint in isolation,
ChromaDB index → verify flow, full pipeline response, streaming endpoint, empty query handling.

---

## CI/CD

The GitHub Actions pipeline runs on every push to `main`, `develop`, `feat/**`, and `fix/**`:

```
lint → test (parallel with build) → build → smoke-test → integration-test
```

Required GitHub secrets: `OPENAI_API_KEY`, `TAVILY_API_KEY`.

---

## Build Phases

- [x] **Phase 1** — Project scaffold, MCP servers (Search + Summarization)
- [x] **Phase 2** — Orchestrator agent (ReWOO planner + MCP gateway + streaming)
- [x] **Phase 3** — Phoenix observability integration
- [x] **Phase 4** — A2A architecture (Supervisor + 3 specialist agents + Knowledge MCP)
- [x] **Phase 5** — CI/CD, unit + integration tests, rich Phoenix span attributes
- [ ] **Phase 6** — GCP deployment (Cloud Run + Terraform)
