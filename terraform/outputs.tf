# ── Service URLs ──────────────────────────────────────────────────────────────

output "orchestrator_url" {
  description = "Public URL of the Orchestrator (main API endpoint)"
  value       = google_cloud_run_v2_service.orchestrator.uri
}

output "search_agent_url" {
  description = "URL of the Search Agent (A2A endpoint)"
  value       = google_cloud_run_v2_service.search_agent.uri
}

output "summarize_agent_url" {
  description = "URL of the Summarize Agent (A2A endpoint)"
  value       = google_cloud_run_v2_service.summarize_agent.uri
}

output "fact_check_agent_url" {
  description = "URL of the Fact-Check Agent (A2A endpoint)"
  value       = google_cloud_run_v2_service.fact_check_agent.uri
}

output "search_mcp_url" {
  description = "URL of the Search MCP server"
  value       = google_cloud_run_v2_service.search_mcp.uri
}

output "summarization_mcp_url" {
  description = "URL of the Summarization MCP server"
  value       = google_cloud_run_v2_service.summarization_mcp.uri
}

output "knowledge_mcp_url" {
  description = "URL of the Knowledge MCP server"
  value       = google_cloud_run_v2_service.knowledge_mcp.uri
}

# ── Infrastructure ────────────────────────────────────────────────────────────

output "database_instance" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.research_agent.name
}

output "database_private_ip" {
  description = "Cloud SQL private IP (reachable only from VPC)"
  value       = google_sql_database_instance.research_agent.private_ip_address
}

output "redis_host" {
  description = "Memorystore Redis host (reachable only from VPC)"
  value       = google_redis_instance.research_agent.host
}

output "artifact_registry" {
  description = "Artifact Registry URL for pushing images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/research-agent"
}

# ── Quick test commands ───────────────────────────────────────────────────────

output "test_commands" {
  description = "Commands to verify the deployment"
  value = <<-EOT
    # Health check
    curl ${google_cloud_run_v2_service.orchestrator.uri}/health

    # Research query
    curl -X POST ${google_cloud_run_v2_service.orchestrator.uri}/research \
      -H "Content-Type: application/json" \
      -d '{"query": "What is the A2A protocol?"}'

    # A2A demo (search agent directly)
    curl -X POST ${google_cloud_run_v2_service.search_agent.uri}/a2a \
      -H "Content-Type: application/json" \
      -d '{"sender":"demo","receiver":"search","task":"search","payload":{"query":"AI agents"}}'
  EOT
}

# ── ChromaDB note ─────────────────────────────────────────────────────────────
# ChromaDB has no managed GCP equivalent. Two options for production:
#
# Option A (simplest): Run ChromaDB as a sidecar in the knowledge-mcp
#   Cloud Run service. Data is ephemeral — resets on cold start.
#   Good enough for a portfolio demo.
#
# Option B (production): Deploy ChromaDB on GKE with a persistent volume,
#   or use a managed vector DB (AlloyDB pgvector, Pinecone, Weaviate Cloud).
#
# This Terraform uses Option A (sidecar via CHROMA_HOST=localhost).
# To switch to Option B, change CHROMA_HOST/CHROMA_PORT in knowledge_mcp
# to point to your external ChromaDB instance.

output "chromadb_note" {
  description = "ChromaDB deployment note"
  value       = "ChromaDB runs as ephemeral storage in knowledge-mcp. For persistent vectors, deploy ChromaDB on GKE or switch to AlloyDB pgvector."
}
