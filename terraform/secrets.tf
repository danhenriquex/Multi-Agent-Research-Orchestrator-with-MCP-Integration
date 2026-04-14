# ── Secret Manager ────────────────────────────────────────────────────────────
# Secrets are created empty here — you populate them once via CLI:
#
#   echo -n "sk-..." | gcloud secrets versions add openai-api-key --data-file=-
#   echo -n "tvly-..." | gcloud secrets versions add tavily-api-key --data-file=-
#   echo -n "yourpassword" | gcloud secrets versions add postgres-password --data-file=-

resource "google_secret_manager_secret" "openai_api_key" {
  secret_id = "openai-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "tavily_api_key" {
  secret_id = "tavily-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "postgres_password" {
  secret_id = "postgres-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# ── Secret version data sources ───────────────────────────────────────────────
# Used by Cloud Run services to reference secrets as env vars.

data "google_secret_manager_secret_version" "openai_api_key" {
  secret  = google_secret_manager_secret.openai_api_key.secret_id
  version = "latest"

  depends_on = [google_secret_manager_secret.openai_api_key]
}

data "google_secret_manager_secret_version" "tavily_api_key" {
  secret  = google_secret_manager_secret.tavily_api_key.secret_id
  version = "latest"

  depends_on = [google_secret_manager_secret.tavily_api_key]
}

data "google_secret_manager_secret_version" "postgres_password" {
  secret  = google_secret_manager_secret.postgres_password.secret_id
  version = "latest"

  depends_on = [google_secret_manager_secret.postgres_password]
}

resource "google_secret_manager_secret" "langsmith_api_key" {
  secret_id = "langsmith-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

data "google_secret_manager_secret_version" "langsmith_api_key" {
  secret  = google_secret_manager_secret.langsmith_api_key.secret_id
  version = "latest"

  depends_on = [google_secret_manager_secret.langsmith_api_key]
}
