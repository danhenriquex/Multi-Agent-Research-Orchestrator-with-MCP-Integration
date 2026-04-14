# ── Cloud SQL (PostgreSQL) ────────────────────────────────────────────────────

resource "google_sql_database_instance" "research_agent" {
  name             = "research-agent-db-${var.environment}"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = var.db_tier

    backup_configuration {
      enabled            = true
      start_time         = "03:00"
      binary_log_enabled = false
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.research_agent.id
    }

    database_flags {
      name  = "max_connections"
      value = "100"
    }
  }

  deletion_protection = var.environment == "prod" ? true : false

  depends_on = [
    google_project_service.apis,
    google_service_networking_connection.private_services,
  ]
}

resource "google_sql_database" "research_agent" {
  name     = var.db_name
  instance = google_sql_database_instance.research_agent.name
}

resource "google_sql_user" "research_agent" {
  name     = var.db_user
  instance = google_sql_database_instance.research_agent.name
  password = data.google_secret_manager_secret_version.postgres_password.secret_data

  depends_on = [google_secret_manager_secret.postgres_password]
}

# ── Connection string used by Cloud Run services ──────────────────────────────

locals {
  database_url = "postgresql://${var.db_user}:${data.google_secret_manager_secret_version.postgres_password.secret_data}@${google_sql_database_instance.research_agent.private_ip_address}:5432/${var.db_name}"
}
