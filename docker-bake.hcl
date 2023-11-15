variable "TAG" {
  default = ""
}

variable "PGADMIN_VERSION" {
  default = "latest"
}

variable "CI_REGISTRY_IMAGE" {
  default = "registry.modoolar.com/modoolar/devops/images/restic-exporter"
}

variable "CI_COMMIT_REF_NAME" {
  default = ""
}

variable "CI_DEFAULT_BRANCH" {
  default = ""
}

group "default" {
  targets = [
    "restic-exporter"
  ]
}

target "restic-exporter" {
  cache-from = ["${CI_REGISTRY_IMAGE}/restic-exporter:latest"]
  tags = [
    equal(CI_COMMIT_REF_NAME, CI_DEFAULT_BRANCH) ? "${CI_REGISTRY_IMAGE}/restic-exporter:latest" : "${CI_REGISTRY_IMAGE}/restic-exporter:${CI_COMMIT_REF_NAME}",
    notequal("", TAG) ? "${CI_REGISTRY_IMAGE}/restic-exporter:${TAG}" : ""
  ]
}
