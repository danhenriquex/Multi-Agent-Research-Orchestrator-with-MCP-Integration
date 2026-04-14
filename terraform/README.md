# Terraform — GCP Deployment

Deploys the full Research Agent stack to Google Cloud Platform using Cloud Run,
Cloud SQL, Memorystore, Artifact Registry, and Secret Manager.

## Architecture

```
Internet
    │
    ▼
Cloud Run: orchestrator          ← public HTTPS endpoint
    │
    │  A2A (HTTPS between Cloud Run services)
    ├──► Cloud Run: search-agent
    │        └──► Cloud Run: search-mcp          ← Tavily + Memorystore Redis
    ├──► Cloud Run: summarize-agent
    │        └──► Cloud Run: summarization-mcp   ← OpenAI API
    └──► Cloud Run: fact-check-agent
             └──► Cloud Run: knowledge-mcp       ← ChromaDB (ephemeral)
    │
    └──► Cloud SQL: PostgreSQL                   ← query history (private VPC)
```

## Prerequisites

```bash
# Install Terraform
brew install terraform   # macOS
# or: https://developer.hashicorp.com/terraform/install

# Install and configure gcloud
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

## First-time setup

### 1. Configure variables

```bash
cp terraform.tfvars.example terraform.tfvars
vim terraform.tfvars   # fill in project_id at minimum
```

### 2. Push your images to Artifact Registry

Run this from the repo root after `make up` has confirmed images build correctly:

```bash
export PROJECT_ID=your-gcp-project-id
export REGION=us-central1
export REGISTRY=${REGION}-docker.pkg.dev/${PROJECT_ID}/research-agent

# Authenticate Docker with GCP
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build and push all images
for service in orchestrator search-agent summarize-agent fact-check-agent search-mcp summarization-mcp knowledge-mcp; do
  # Map service name to dockerfile path
  case $service in
    orchestrator)       dockerfile="src/orchestrator/Dockerfile" ;;
    search-agent)       dockerfile="src/agents/search/Dockerfile" ;;
    summarize-agent)    dockerfile="src/agents/summarize/Dockerfile" ;;
    fact-check-agent)   dockerfile="src/agents/fact_check/Dockerfile" ;;
    search-mcp)         dockerfile="src/mcp_servers/search/Dockerfile" ;;
    summarization-mcp)  dockerfile="src/mcp_servers/summarization/Dockerfile" ;;
    knowledge-mcp)      dockerfile="src/mcp_servers/knowledge/Dockerfile" ;;
  esac

  docker build -t ${REGISTRY}/${service}:latest -f ${dockerfile} .
  docker push ${REGISTRY}/${service}:latest
done
```

### 3. Populate secrets

```bash
echo -n "sk-..." | gcloud secrets versions add openai-api-key --data-file=-
echo -n "tvly-..." | gcloud secrets versions add tavily-api-key --data-file=-
echo -n "$(openssl rand -base64 32)" | gcloud secrets versions add postgres-password --data-file=-
```

### 4. Deploy

```bash
terraform init
terraform plan     # review what will be created
terraform apply    # type 'yes' to confirm (~10 minutes first time)
```

### 5. Verify

```bash
# Terraform prints the orchestrator URL at the end — test it:
curl $(terraform output -raw orchestrator_url)/health

# Run a query
curl -X POST $(terraform output -raw orchestrator_url)/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the A2A protocol?"}'
```

## Update deployment

```bash
# After code changes: rebuild + push images, then redeploy
docker build -t ${REGISTRY}/orchestrator:latest -f src/orchestrator/Dockerfile .
docker push ${REGISTRY}/orchestrator:latest

# Force Cloud Run to pull the new image
terraform apply -var="image_tag=latest"

# Or use a specific git SHA for immutable tags (recommended)
GIT_SHA=$(git rev-parse --short HEAD)
docker build -t ${REGISTRY}/orchestrator:${GIT_SHA} ...
terraform apply -var="image_tag=${GIT_SHA}"
```

## Tear down

```bash
terraform destroy   # removes ALL resources — including database
```

## Cost estimate (us-central1, idle stack)

| Resource | Monthly cost |
|---|---|
| Cloud Run (7 services, scale-to-zero) | ~$0 idle, ~$5–15 under load |
| Cloud SQL db-f1-micro | ~$10 |
| Memorystore 1GB Basic | ~$35 |
| Artifact Registry | ~$1 |
| **Total** | **~$46–56/month** |

To reduce cost: set `min_instances = 0` (already default) and delete the stack when not in use.
Memorystore is the biggest cost — swap for a free Redis via Upstash if needed.
