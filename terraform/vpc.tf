# ── VPC network ───────────────────────────────────────────────────────────────
# Cloud Run needs a VPC connector to reach Memorystore (Redis) and
# Cloud SQL on private IPs.

resource "google_compute_network" "research_agent" {
  name                    = "research-agent-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "research_agent" {
  name          = "research-agent-subnet"
  ip_cidr_range = "10.0.0.0/24"
  region        = var.region
  network       = google_compute_network.research_agent.id
}

# Reserved range for Google-managed services (Cloud SQL private IP)
resource "google_compute_global_address" "private_services" {
  name          = "research-agent-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.research_agent.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.research_agent.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]

  depends_on = [google_project_service.apis]
}

# VPC connector so Cloud Run services can reach private IPs
resource "google_vpc_access_connector" "research_agent" {
  name          = "research-agent-connector"
  region        = var.region
  ip_cidr_range = "10.8.0.0/28"
  network       = google_compute_network.research_agent.name
  min_instances = 2
  max_instances = 3

  depends_on = [google_project_service.apis]
}
