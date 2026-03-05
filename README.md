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
| --- | --- | --- |
| No multi-turn memory | Keeps state trivial | Add Cloud SQL sessions |
| Synchronous MCP calls | Easier to debug | Add asyncio.gather() once stable |
| No circuit breakers | Reduce initial complexity | Add after load testing |

## Quick Start

```bash
# 1. Setup
./scripts/setup.sh

# 2. Add API keys to .env
vim .env

# 3. Start all services
docker compose up --build

# 4. Verify services
./scripts/test_services.sh

# 5. Run a research query (streaming)
curl -N -X POST http://localhost:8000/research \
  -H 'Content-Type: application/json' \
  -d '{"query": "What is Model Context Protocol and why does it matter?"}'
```

## Services

| Service | URL | Purpose |
| --- | --- | --- |
| Orchestrator | <http://localhost:8000> | Main API + agent loop |
| Search MCP | <http://localhost:8001> | Web search tool server |
| Summarization MCP | <http://localhost:8002> | Text synthesis tool server |
| Phoenix UI | <http://localhost:6006> | Distributed tracing + spans |
| Redis | localhost:6379 | Search result cache |
| PostgreSQL | localhost:5432 | Query history |

## Observability

Open Phoenix at <http://localhost:6006> to see:

- Agent reasoning loop spans
- MCP server call latencies
- Tool selection frequency
- Planning vs execution time ratio

## Build Phases

- [x] **Phase 1** – Project scaffold, MCP servers (Search + Summarization)
- [ ] **Phase 2** – Orchestrator agent (ReWOO planner + MCP gateway + streaming)
- [ ] **Phase 3** – Phoenix observability integration
- [ ] **Phase 4** – GCP deployment (Cloud Run + Terraform)
- [ ] **Phase 5** – Portfolio polish (load tests, architecture diagrams)
# Multi-Agent-Research-Orchestrator-with-MCP-Integration
