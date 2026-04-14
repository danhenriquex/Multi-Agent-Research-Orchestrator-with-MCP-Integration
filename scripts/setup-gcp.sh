#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup-gcp.sh — One-shot GCP deployment script for Research Agent
# Run from the repo root: ./scripts/setup-gcp.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}✓${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✗${NC} $*"; exit 1; }
section() { echo -e "\n${BOLD}── $* ──────────────────────────────────────────${NC}"; }

# ── 1. Load config ────────────────────────────────────────────────────────────
section "Configuration"

PROJECT_ID=${GCP_PROJECT_ID:-""}
REGION=${GCP_REGION:-"us-central1"}

if [ -z "$PROJECT_ID" ]; then
    # Try to read from terraform.tfvars
    if [ -f terraform/terraform.tfvars ]; then
        PROJECT_ID=$(grep "project_id" terraform/terraform.tfvars | cut -d'"' -f2)
    fi
fi

if [ -z "$PROJECT_ID" ]; then
    error "GCP_PROJECT_ID not set. Run: export GCP_PROJECT_ID=your-project-id"
fi

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/research-agent"

info "Project:  $PROJECT_ID"
info "Region:   $REGION"
info "Registry: $REGISTRY"

# ── 2. Check prerequisites ────────────────────────────────────────────────────
section "Checking prerequisites"

command -v gcloud    &>/dev/null || error "gcloud not found — install: https://cloud.google.com/sdk/docs/install"
command -v terraform &>/dev/null || error "terraform not found — install: https://developer.hashicorp.com/terraform/install"
command -v docker    &>/dev/null || error "docker not found"

gcloud config set project "$PROJECT_ID" &>/dev/null
info "gcloud project set to $PROJECT_ID"

# ── 3. Load API keys from .env ───────────────────────────────────────────────
section "API Keys"

ENV_FILE="${ENV_FILE:-.env}"

if [ ! -f "$ENV_FILE" ]; then
    error ".env file not found. Create one from .env.example: cp .env.example .env"
fi

# Parse .env — ignore comments and empty lines
parse_env() {
    local key=$1
    grep "^${key}=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'"
}

OPENAI_KEY=$(parse_env "OPENAI_API_KEY")
TAVILY_KEY=$(parse_env "TAVILY_API_KEY")
LANGSMITH_KEY=$(parse_env "LANGSMITH_API_KEY")

[ -z "$OPENAI_KEY" ]  && error "OPENAI_API_KEY not found in $ENV_FILE"
[ -z "$TAVILY_KEY" ]  && error "TAVILY_API_KEY not found in $ENV_FILE"

info "Loaded OPENAI_API_KEY from $ENV_FILE"
info "Loaded TAVILY_API_KEY from $ENV_FILE"
[ -n "$LANGSMITH_KEY" ] && info "Loaded LANGSMITH_API_KEY from $ENV_FILE" || warn "LANGSMITH_API_KEY not found — LangSmith tracing will be disabled"

# ── 4. Terraform init + apply (infrastructure only) ──────────────────────────
section "Terraform — enabling APIs and creating infrastructure"

cd terraform
terraform init -upgrade 2>/dev/null | tail -3

info "Running terraform apply — this takes 10-15 minutes (Cloud SQL is slow)"
terraform apply -auto-approve
cd ..

info "Infrastructure created"

# ── 5. Populate secrets ───────────────────────────────────────────────────────
section "Populating Secret Manager"

echo -n "$OPENAI_KEY" | gcloud secrets versions add openai-api-key --data-file=- 2>/dev/null \
    && info "openai-api-key set" \
    || warn "openai-api-key may already have a version — skipping"

echo -n "$TAVILY_KEY" | gcloud secrets versions add tavily-api-key --data-file=- 2>/dev/null \
    && info "tavily-api-key set" \
    || warn "tavily-api-key may already have a version — skipping"

if [ -n "$LANGSMITH_KEY" ]; then
    echo -n "$LANGSMITH_KEY" | gcloud secrets versions add langsmith-api-key --data-file=- 2>/dev/null \
        && info "langsmith-api-key set" \
        || warn "langsmith-api-key may already have a version — skipping"
else
    # Set a placeholder so Terraform doesn't fail reading the secret version
    echo -n "disabled" | gcloud secrets versions add langsmith-api-key --data-file=- 2>/dev/null || true
    warn "LangSmith key skipped — tracing will be disabled"
fi

POSTGRES_PASS=$(openssl rand -base64 32)
echo -n "$POSTGRES_PASS" | gcloud secrets versions add postgres-password --data-file=- 2>/dev/null \
    && info "postgres-password generated and set" \
    || warn "postgres-password may already have a version — skipping"

# ── 6. Authenticate Docker with Artifact Registry ────────────────────────────
section "Docker → Artifact Registry authentication"

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
info "Docker authenticated with Artifact Registry"

# ── 7. Build and push all images ──────────────────────────────────────────────
section "Building and pushing Docker images"

declare -A DOCKERFILES=(
    ["orchestrator"]="src/orchestrator/Dockerfile"
    ["search-agent"]="src/agents/search/Dockerfile"
    ["summarize-agent"]="src/agents/summarize/Dockerfile"
    ["fact-check-agent"]="src/agents/fact_check/Dockerfile"
    ["search-mcp"]="src/mcp_servers/search/Dockerfile"
    ["summarization-mcp"]="src/mcp_servers/summarization/Dockerfile"
    ["knowledge-mcp"]="src/mcp_servers/knowledge/Dockerfile"
)

for service in orchestrator search-agent summarize-agent fact-check-agent search-mcp summarization-mcp knowledge-mcp; do
    dockerfile="${DOCKERFILES[$service]}"
    image="${REGISTRY}/${service}:latest"

    echo -n "  Building $service... "
    docker build -t "$image" -f "$dockerfile" . --quiet \
        && echo -e "${GREEN}built${NC}" \
        || error "Failed to build $service"

    echo -n "  Pushing $service... "
    docker push "$image" --quiet \
        && echo -e "${GREEN}pushed${NC}" \
        || error "Failed to push $service"
done

info "All images pushed to Artifact Registry"

# ── 8. Deploy Cloud Run services ──────────────────────────────────────────────
section "Deploying Cloud Run services"

cd terraform
terraform apply -auto-approve
cd ..

# ── 9. Verify ─────────────────────────────────────────────────────────────────
section "Verifying deployment"

ORCHESTRATOR_URL=$(cd terraform && terraform output -raw orchestrator_url)

echo -n "  Checking orchestrator health... "
HEALTH=$(curl -sf "${ORCHESTRATOR_URL}/health" 2>/dev/null || echo "")

if [ -n "$HEALTH" ]; then
    echo -e "${GREEN}OK${NC}"
    echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
else
    warn "Orchestrator not responding yet — Cloud Run may still be starting (wait 30s and retry)"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Deployment complete!${NC}"
echo -e "${BOLD}════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Orchestrator URL: $ORCHESTRATOR_URL"
echo ""
echo "  Test commands:"
echo "    curl ${ORCHESTRATOR_URL}/health"
echo "    curl -X POST ${ORCHESTRATOR_URL}/research \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"query\": \"What is the A2A protocol?\"}'"
echo ""
echo "  To tear down:"
echo "    cd terraform && terraform destroy"
echo ""
