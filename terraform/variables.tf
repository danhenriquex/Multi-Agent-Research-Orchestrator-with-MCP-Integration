# ── Project ────────────────────────────────────────────────────────────────────

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

# ── Container images ──────────────────────────────────────────────────────────

variable "image_tag" {
  description = "Docker image tag to deploy (e.g. git SHA or 'latest')"
  type        = string
  default     = "latest"
}

locals {
  registry = "us-central1-docker.pkg.dev/${var.project_id}/research-agent"

  images = {
    orchestrator      = "${local.registry}/orchestrator:${var.image_tag}"
    search_agent      = "${local.registry}/search-agent:${var.image_tag}"
    summarize_agent   = "${local.registry}/summarize-agent:${var.image_tag}"
    fact_check_agent  = "${local.registry}/fact-check-agent:${var.image_tag}"
    search_mcp        = "${local.registry}/search-mcp:${var.image_tag}"
    summarization_mcp = "${local.registry}/summarization-mcp:${var.image_tag}"
    knowledge_mcp     = "${local.registry}/knowledge-mcp:${var.image_tag}"
  }
}

# ── Cache & Embeddings ────────────────────────────────────────────────────────

variable "embedding_model" {
  description = "OpenAI embedding model for semantic cache and ChromaDB"
  type        = string
  default     = "text-embedding-3-small"
}

variable "cache_similarity_threshold" {
  description = "Semantic cache similarity threshold (0.90-0.97)"
  type        = string
  default     = "0.94"
}

variable "chroma_drift_threshold" {
  description = "ChromaDB drift detection threshold"
  type        = string
  default     = "0.30"
}

variable "chroma_verify_threshold" {
  description = "ChromaDB minimum similarity to verify a claim"
  type        = string
  default     = "0.75"
}

# ── Scaling ───────────────────────────────────────────────────────────────────

variable "min_instances" {
  description = "Minimum Cloud Run instances (0 = scale to zero)"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum Cloud Run instances per service"
  type        = number
  default     = 3
}

# ── Database ──────────────────────────────────────────────────────────────────

variable "db_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-f1-micro"
}

variable "db_name" {
  description = "Postgres database name"
  type        = string
  default     = "research_agent"
}

variable "db_user" {
  description = "Postgres user"
  type        = string
  default     = "agent"
}
