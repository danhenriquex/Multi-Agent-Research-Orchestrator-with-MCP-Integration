# ── Shared Cloud Run configuration ────────────────────────────────────────────

locals {
  # Common env vars injected into every Cloud Run service
  common_env = [
    {
      name  = "LOG_LEVEL"
      value = "INFO"
    },
  ]

  # VPC connector config shared across all services
  vpc_access = {
    connector = google_vpc_access_connector.research_agent.id
    egress    = "PRIVATE_RANGES_ONLY"
  }
}

# ── MCP Servers ───────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "search_mcp" {
  name     = "search-mcp"
  location = var.region

  template {
    service_account = google_service_account.research_agent.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.research_agent.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = local.images.search_mcp

      ports {
        container_port = 8001
      }

      env {
        name  = "MCP_SERVER_PORT"
        value = "8001"
      }
      env {
        name  = "REDIS_URL"
        value = local.redis_url
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = var.embedding_model
      }
      env {
        name  = "CACHE_NAMESPACE"
        value = var.environment
      }
      env {
        name  = "CACHE_SIMILARITY_THRESHOLD"
        value = var.cache_similarity_threshold
      }
      env {
        name = "TAVILY_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.tavily_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "PHOENIX_COLLECTOR_ENDPOINT"
        value = "http://localhost:4317"  # disabled in Cloud Run — no Phoenix deployed
      }
      env {
        name  = "OTEL_SDK_DISABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_vpc_access_connector.research_agent,
    google_redis_instance.research_agent,
  ]
}

resource "google_cloud_run_v2_service" "summarization_mcp" {
  name     = "summarization-mcp"
  location = var.region

  template {
    service_account = google_service_account.research_agent.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.images.summarization_mcp

      ports {
        container_port = 8002
      }

      env {
        name  = "MCP_SERVER_PORT"
        value = "8002"
      }
      env {
        name  = "MAX_TOKENS_PER_REQUEST"
        value = "2000"
      }
            env {
        name  = "LANGCHAIN_TRACING_V2"
        value = "true"
      }
      env {
        name = "LANGCHAIN_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.langsmith_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "LANGCHAIN_PROJECT"
        value = "research-agent"
      }
      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.openai_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "PHOENIX_COLLECTOR_ENDPOINT"
        value = "http://localhost:4317"  # disabled in Cloud Run — no Phoenix deployed
      }
      env {
        name  = "OTEL_SDK_DISABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service" "knowledge_mcp" {
  name     = "knowledge-mcp"
  location = var.region

  template {
    service_account = google_service_account.research_agent.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.images.knowledge_mcp

      ports {
        container_port = 8003
      }

      env {
        name  = "MCP_SERVER_PORT"
        value = "8003"
      }
      env {
        name  = "CHROMA_HOST"
        value = "localhost"  # sidecar pattern — see note in outputs.tf
      }
      env {
        name  = "CHROMA_PORT"
        value = "8000"
      }
      env {
        name  = "CHROMA_COLLECTION"
        value = "research_knowledge"
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = var.embedding_model
      }
      env {
        name  = "CHROMA_DRIFT_THRESHOLD"
        value = var.chroma_drift_threshold
      }
      env {
        name  = "CHROMA_VERIFY_THRESHOLD"
        value = var.chroma_verify_threshold
      }
      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.openai_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "PHOENIX_COLLECTOR_ENDPOINT"
        value = "http://localhost:4317"  # disabled in Cloud Run — no Phoenix deployed
      }
      env {
        name  = "OTEL_SDK_DISABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# ── A2A Agents ────────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "search_agent" {
  name     = "search-agent"
  location = var.region

  template {
    service_account = google_service_account.research_agent.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.images.search_agent

      ports {
        container_port = 8010
      }

      env {
        name  = "AGENT_PORT"
        value = "8010"
      }
      env {
        name  = "SEARCH_MCP_URL"
        value = google_cloud_run_v2_service.search_mcp.uri
      }
      env {
        name  = "PHOENIX_COLLECTOR_ENDPOINT"
        value = "http://localhost:4317"  # disabled in Cloud Run — no Phoenix deployed
      }
      env {
        name  = "OTEL_SDK_DISABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_service.search_mcp,
  ]
}

resource "google_cloud_run_v2_service" "summarize_agent" {
  name     = "summarize-agent"
  location = var.region

  template {
    service_account = google_service_account.research_agent.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.images.summarize_agent

      ports {
        container_port = 8011
      }

      env {
        name  = "AGENT_PORT"
        value = "8011"
      }
      env {
        name  = "SUMMARIZATION_MCP_URL"
        value = google_cloud_run_v2_service.summarization_mcp.uri
      }
      env {
        name  = "PHOENIX_COLLECTOR_ENDPOINT"
        value = "http://localhost:4317"  # disabled in Cloud Run — no Phoenix deployed
      }
      env {
        name  = "OTEL_SDK_DISABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_service.summarization_mcp,
  ]
}

resource "google_cloud_run_v2_service" "fact_check_agent" {
  name     = "fact-check-agent"
  location = var.region

  template {
    service_account = google_service_account.research_agent.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.images.fact_check_agent

      ports {
        container_port = 8012
      }

      env {
        name  = "AGENT_PORT"
        value = "8012"
      }
      env {
        name  = "KNOWLEDGE_MCP_URL"
        value = google_cloud_run_v2_service.knowledge_mcp.uri
      }
      env {
        name  = "PHOENIX_COLLECTOR_ENDPOINT"
        value = "http://localhost:4317"  # disabled in Cloud Run — no Phoenix deployed
      }
      env {
        name  = "OTEL_SDK_DISABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_service.knowledge_mcp,
  ]
}

# ── Orchestrator (deployed last — needs all agent URLs) ───────────────────────

resource "google_cloud_run_v2_service" "orchestrator" {
  name     = "orchestrator"
  location = var.region

  template {
    service_account = google_service_account.research_agent.email
    timeout         = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    vpc_access {
      connector = google_vpc_access_connector.research_agent.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = local.images.orchestrator

      ports {
        container_port = 8000
      }

      env {
        name  = "MODEL"
        value = "gpt-4o-mini"
      }
      env {
        name  = "SEARCH_AGENT_URL"
        value = google_cloud_run_v2_service.search_agent.uri
      }
      env {
        name  = "SUMMARIZE_AGENT_URL"
        value = google_cloud_run_v2_service.summarize_agent.uri
      }
      env {
        name  = "FACT_CHECK_AGENT_URL"
        value = google_cloud_run_v2_service.fact_check_agent.uri
      }
      env {
        name  = "DB_HOST"
        value = google_sql_database_instance.research_agent.private_ip_address
      }
      env {
        name  = "DB_NAME"
        value = var.db_name
      }
      env {
        name  = "DB_USER"
        value = var.db_user
      }
      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.postgres_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.openai_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "LANGCHAIN_TRACING_V2"
        value = "true"
      }
      env {
        name = "LANGCHAIN_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.langsmith_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "LANGCHAIN_PROJECT"
        value = "research-agent"
      }
      env {
        name  = "PHOENIX_COLLECTOR_ENDPOINT"
        value = "http://localhost:4317"  # disabled in Cloud Run — no Phoenix deployed
      }
      env {
        name  = "OTEL_SDK_DISABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_service.search_agent,
    google_cloud_run_v2_service.summarize_agent,
    google_cloud_run_v2_service.fact_check_agent,
    google_sql_database_instance.research_agent,
    google_vpc_access_connector.research_agent,
  ]
}

# ── IAM: make all services publicly accessible ────────────────────────────────
# Remove these for private deployments and use Cloud Armor / IAP instead.

# IAM managed outside Terraform to prevent overwriting manual changes




# ── IAM: public access for all services ──────────────────────────────────────
locals {
  public_services = [
    google_cloud_run_v2_service.orchestrator.name,
    google_cloud_run_v2_service.search_agent.name,
    google_cloud_run_v2_service.summarize_agent.name,
    google_cloud_run_v2_service.fact_check_agent.name,
    google_cloud_run_v2_service.search_mcp.name,
    google_cloud_run_v2_service.summarization_mcp.name,
    google_cloud_run_v2_service.knowledge_mcp.name,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_access" {
  for_each = toset(local.public_services)
  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = "allUsers"
}
