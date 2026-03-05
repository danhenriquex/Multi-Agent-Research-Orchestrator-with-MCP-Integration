#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# init.sh — First-time project bootstrap
# Installs uv, syncs dependencies, sets up pre-commit, and creates .env
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
section() { echo -e "\n${BOLD}$*${NC}"; }

# ── 1. Install uv if missing ──────────────────────────────────────────────────
section "=== Research Agent – Init ==="

if ! command -v uv &> /dev/null; then
    warn "'uv' not found. Installing via official script..."
    if command -v curl &> /dev/null; then
        curl -Ls https://astral.sh/uv/install.sh | bash
    elif command -v wget &> /dev/null; then
        wget -qO- https://astral.sh/uv/install.sh | bash
    else
        error "Neither curl nor wget found. Install one and retry."
    fi

    # Add cargo/uv to PATH for this session
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

    command -v uv &> /dev/null || error "uv installation failed. Install manually: https://docs.astral.sh/uv/"
    info "uv installed: $(uv --version)"
else
    info "uv already installed: $(uv --version)"
fi

# ── 2. Sync Python dependencies ───────────────────────────────────────────────
section "Syncing Python dependencies..."
uv sync --all-groups
info "Dependencies synced"

# ── 3. Pre-commit hooks ───────────────────────────────────────────────────────
section "Installing pre-commit hooks..."
if uv run -- pre-commit install; then
    info "pre-commit hooks installed"
else
    warn "pre-commit install failed — skipping (non-fatal)"
fi

# ── 4. Create .env from example ──────────────────────────────────────────────
section "Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    info "Created .env from .env.example"
    echo ""
    echo -e "  ${YELLOW}ACTION REQUIRED:${NC} Edit .env and set your API keys:"
    echo "    ANTHROPIC_API_KEY=sk-ant-..."
    echo "    TAVILY_API_KEY=tvly-..."
    echo ""
    echo "  Get keys from:"
    echo "    • Anthropic: https://console.anthropic.com"
    echo "    • Tavily:    https://app.tavily.com"
else
    info ".env already exists — skipping (delete it to reset)"
fi

# ── 5. Check Docker ───────────────────────────────────────────────────────────
section "Checking Docker..."
if docker info &> /dev/null; then
    info "Docker is running"
else
    warn "Docker does not appear to be running"
    warn "Start Docker Desktop (or dockerd) before running 'make up'"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Setup complete! Next steps:${NC}"
echo "  1. Edit .env with your API keys  →  vim .env"
echo "  2. Start all services            →  make up"
echo "  3. Verify health                 →  make health"
echo "  4. Run a research query          →  make query Q=\"What is MCP?\""
echo "  5. Open observability UI         →  http://localhost:6006"