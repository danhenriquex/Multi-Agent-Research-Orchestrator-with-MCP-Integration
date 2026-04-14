# Research Agent System

A production-grade multi-agent research system demonstrating senior-level AI engineering patterns:
A2A agent orchestration, MCP protocol abstraction, graceful degradation, streaming responses,
distributed tracing, LLM-as-a-judge evaluation, and LangSmith observability.

```text
┌─────────────────────┐
│  Supervisor Agent   │  ReWOO planner + A2A orchestration
│    (Orchestrator)   │  LangSmith tracing (@traceable)
└─────────┬───────────┘
          │
     A2A Protocol (Agent ↔ Agent)
          │
┌─────────┼─────────────────────────┐
│         │                         │
┌─────────▼──────┐  ┌───────────────▼──┐  ┌──────────────────┐
│  Search Agent  │  │ Summarize Agent  │  │ Fact-Check Agent │
│    :8010       │  │    :8011         │  │    :8012         │
└────────┬───────┘  └────────┬─────────┘  └────────┬─────────┘
         │                   │                      │
    MCP Protocol        MCP Protocol           MCP Protocol
    (Agent ↔ Tool)     (Agent ↔ Tool)         (Agent ↔ Tool)
         │                   │                      │
┌────────▼───────┐  ┌────────▼─────────┐  ┌────────▼─────────┐
│   Search MCP   │  │ Summarization MCP│  │  Knowledge MCP   │
│    :8001       │  │    :8002         │  │    :8003         │
│  [Tavily API]  │  │  [OpenAI API]    │  │  [ChromaDB]      │
└────────────────┘  └──────────────────┘  └──────────────────┘

Observable via Phoenix (LLM spans + eval scores) + LangSmith (prompt/token traces)
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
- Easier to instrument with OpenTelemetry spans + LangSmith `@traceable`

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
#    LANGSMITH_API_KEY=ls__...   (optional)
#    LANGCHAIN_TRACING_V2=true   (optional)
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

# 8. Open Phoenix to see distributed traces + eval scores
make phoenix

# 9. Run LLM-as-a-judge evaluators
make evals
```

---

## Services

| Service | URL | Purpose |
|---|---|---|
| Orchestrator | http://localhost:8000 | Supervisor agent + API |
| Search Agent | http://localhost:8010 | A2A agent → Search MCP |
| Summarize Agent | http://localhost:8011 | A2A agent → Summarization MCP |
| Fact-Check Agent | http://localhost:8012 | A2A agent → Knowledge MCP |
| Search MCP | http://localhost:8001 | Tavily web search tool server |
| Summarization MCP | http://localhost:8002 | OpenAI synthesis tool server |
| Knowledge MCP | http://localhost:8003 | ChromaDB vector search |
| Phoenix UI | http://localhost:6006 | Distributed tracing + eval scores |
| ChromaDB | http://localhost:8100 | Vector knowledge base |
| Redis | localhost:6379 | Search result cache |
| PostgreSQL | localhost:5432 | Query history |

---

## Make Commands

```bash
# ── Setup ─────────────────────────────────────────────────────────────────────
make init                          # bootstrap project (uv, deps, pre-commit, .env)

# ── Docker ────────────────────────────────────────────────────────────────────
make up                            # start all services (2 min timeout)
make down                          # stop all services
make down-volumes                  # stop and remove volumes (DESTRUCTIVE)
make restart                       # restart all services
make status                        # show status of all containers
make rebuild s=search-agent        # rebuild and restart one service
make rebuild-clean s=search-agent  # force rebuild with no cache

# ── Queries ───────────────────────────────────────────────────────────────────
make query Q="your question"         # run a full research query
make query-stream Q="your question"  # stream agent steps in real time

# ── A2A Testing ───────────────────────────────────────────────────────────────
make a2a-demo                      # call search agent directly via A2A
make a2a-factcheck                 # call fact-check agent directly via A2A
make agents-health                 # health check all 3 A2A agents

# ── Health & Observability ────────────────────────────────────────────────────
make health                        # check health of orchestrator + MCP servers
make phoenix                       # open Phoenix tracing UI in browser
make debug                         # show logs for phoenix and orchestrator

# ── Evals ─────────────────────────────────────────────────────────────────────
make evals                         # run all LLM-as-a-judge evaluators
make evals-dry                     # count spans without LLM calls (free)
make evals-summary                 # run only summary clarity evaluator

# ── Database ──────────────────────────────────────────────────────────────────
make db-shell                      # open psql shell on Postgres
make db-history                    # show last 10 research queries

# ── Cache ─────────────────────────────────────────────────────────────────────
make cache-flush                   # flush all Redis search cache entries
make cache-stats                   # show Redis memory usage and key count

# ── Tests ─────────────────────────────────────────────────────────────────────
make test                          # run unit tests
make test-cov                      # run unit tests with coverage report
make test-integration              # run integration tests (requires: make up)

# ── GCP Deployment ────────────────────────────────────────────────────────────
make deploy-gcp                    # full GCP deployment (reads keys from .env)
make post-deploy                   # run once after terraform apply — IAM, DB schema

# ── Dev ───────────────────────────────────────────────────────────────────────
make lint                          # run ruff linter
make format                        # run ruff formatter
make docker-prune                  # remove unused Docker resources
```

---

## Observability

### Phoenix (`http://localhost:6006`)

Open Phoenix after running queries. Switch to **All** spans (not Root Spans) and filter by
`span_kind == 'LLM'` to see native LLM spans with token counts and prompt/completion pairs.

Each custom span shows:

- **Search Agent**: `input.query`, `output.num_results`, `output.backend`, top 3 result titles + URLs
- **Summarize Agent**: `input.source_urls`, `output.summary_preview` (first 500 chars), `output.input_tokens`
- **Fact-Check Agent**: `input.summary_preview`, `output.confidence`, `output.verified`, `output.flags`
- **ReWOO Planner**: `input.query`, `output.num_steps`, `output.plan`

Project-level aggregate eval scores appear in the header:

- **Search Quality** — % of searches returning results from a reliable backend
- **Summary Clarity** — % of summaries rated clear by GPT-4o-mini judge
- **Fact Check Confidence** — distribution of confidence scores across KB lookups

### LangSmith (`https://smith.langchain.com`)

Traces for every OpenAI call — planner and summarization — with full prompt/response pairs,
token counts, and latency. Set `LANGSMITH_API_KEY` and `LANGCHAIN_TRACING_V2=true` in `.env`.

### GCP Cloud Logging

When deployed to GCP, all structured logs from every service are automatically available at:
```
https://console.cloud.google.com/logs?project=YOUR_PROJECT_ID
```

Filter by service:
```
resource.type=cloud_run_revision AND resource.labels.service_name=orchestrator
```

---

## Evaluation

```bash
# Run a few queries first
make query Q="What is the A2A protocol?"
make query Q="What is Model Context Protocol?"
make query Q="What are best practices for multi-agent systems?"

# Run LLM-as-a-judge evaluators (reads spans from Phoenix, logs scores back)
export $(cat .env | grep -v '^#' | xargs) && make evals
```

Four evaluators run automatically:

1. **Plan Quality** (LLM judge) — did the ReWOO planner generate a sensible research plan?
2. **Summary Clarity** (LLM judge) — is the summary clear and directly answers the query?
3. **Fact-Check Confidence** (rule-based) — is the ChromaDB confidence score meaningful?
4. **Search Quality** (rule-based) — did the search return results from a reliable backend?

Scores appear attached to each span in Phoenix under the **Annotations** column.

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
Optional: `LANGSMITH_API_KEY` (enables LangSmith tracing in CI).

---

## GCP Deployment

The full stack deploys to Google Cloud Platform using Terraform. Each Docker service maps to
a Cloud Run service, with Cloud SQL replacing local Postgres and Memorystore replacing Redis.

```
Local                     GCP
─────────────────────     ──────────────────────────────────
7 Docker containers   →   7 Cloud Run services (scale to zero)
postgres container    →   Cloud SQL (managed Postgres 16)
redis container       →   Memorystore (managed Redis 7)
local images          →   Artifact Registry
.env file             →   Secret Manager
localhost:8000        →   https://orchestrator-xxx-uc.a.run.app
```

### Prerequisites

```bash
# Install Terraform
sudo apt install terraform

# Install and authenticate gcloud
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# Link billing
gcloud billing projects link YOUR_PROJECT_ID \
  --billing-account=YOUR_BILLING_ACCOUNT_ID
```

### Deploy

```bash
# 1. Configure Terraform
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# fill in project_id

# 2. Populate secrets first (before terraform apply)
source .env
echo -n "$OPENAI_API_KEY"    | gcloud secrets versions add openai-api-key --data-file=-
echo -n "$TAVILY_API_KEY"    | gcloud secrets versions add tavily-api-key --data-file=-
echo -n "$LANGSMITH_API_KEY" | gcloud secrets versions add langsmith-api-key --data-file=-
echo -n "$(openssl rand -base64 32)" | gcloud secrets versions add postgres-password --data-file=-

# 3. Build and push Docker images
export GCP_PROJECT_ID=YOUR_PROJECT_ID
make deploy-gcp

# 4. Post-deploy configuration (IAM, DB schema, Cloud SQL auth)
make post-deploy

# 5. Test
curl $(cd terraform && terraform output -raw orchestrator_url)/health
```

### Test the live deployment

```bash
curl -X POST $(cd terraform && terraform output -raw orchestrator_url)/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the A2A protocol?"}'
```

### Cost estimate (us-central1, idle)

| Resource | Monthly cost |
|---|---|
| Cloud Run (7 services, scale-to-zero) | ~$0 idle, ~$5–15 under load |
| Cloud SQL db-f1-micro | ~$10 |
| Memorystore 1GB Basic | ~$35 |
| Artifact Registry | ~$1 |
| **Total** | **~$46–56/month** |

### Tear down

```bash
# Disable deletion protection first
gcloud sql instances patch research-agent-db-prod \
  --no-deletion-protection --project=YOUR_PROJECT_ID

cd terraform && terraform destroy
```

Redeploy later with just `terraform apply` — images stay in Artifact Registry so no rebuild needed.

---

## Build Phases

- [x] **Phase 1** — Project scaffold, MCP servers (Search + Summarization)
- [x] **Phase 2** — Orchestrator agent (ReWOO planner + MCP gateway + streaming)
- [x] **Phase 3** — Phoenix observability integration
- [x] **Phase 4** — A2A architecture (Supervisor + 3 specialist agents + Knowledge MCP)
- [x] **Phase 5** — CI/CD, unit + integration tests, rich Phoenix span attributes
- [x] **Phase 6** — LangSmith tracing, LLM-as-a-judge evals, OpenAI auto-instrumentation
- [x] **Phase 7** — GCP deployment (Cloud Run + Terraform + scripts)
