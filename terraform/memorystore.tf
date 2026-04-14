# ── Memorystore (Redis) ───────────────────────────────────────────────────────

resource "google_redis_instance" "research_agent" {
  name               = "research-agent-cache-${var.environment}"
  tier               = "BASIC"
  memory_size_gb     = 1
  region             = var.region
  authorized_network = google_compute_network.research_agent.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  redis_version      = "REDIS_7_0"

  display_name = "Research Agent Search Cache"

  labels = {
    environment = var.environment
    project     = "research-agent"
  }

  depends_on = [
    google_project_service.apis,
    google_service_networking_connection.private_services,
  ]
}

locals {
  redis_url = "redis://${google_redis_instance.research_agent.host}:${google_redis_instance.research_agent.port}"
}
