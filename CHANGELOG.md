# Changelog

## 2.0.0 (2025/12/09)

* Added more global statistics for the repository:
  * You can disable this feature with the "NO_GLOBAL_STATS" env var
  * Added new metrics: "restic_size_total", "restic_uncompressed_size_total", "restic_compression_ratio",
"restic_blob_count_total"
* New method of getting per backup statistics:
  * For clients with Restic >= 0.17 it is much faster and it is always enabled
  * For older clients we use the previous method. The "NO_STATS" env var has been renamed to "NO_LEGACY_STATS"
  * The value of "restic_backup_files_total" has been fixed. The value provided by "restic stats" was wrong
  * Added new metrics per backup: "restic_backup_files_new", "restic_backup_files_changed",
"restic_backup_files_unmodified", "restic_backup_dirs_new", "restic_backup_dirs_changed",
"restic_backup_dirs_unmodified", "restic_backup_data_added_bytes", "restic_backup_duration_seconds"
* Support "RESTIC_PASSWORD_COMMAND" env var for repository password configuration
* Change the default value of "REFRESH_INTERVAL" env var to 3600 (1 hour)
* Include Restic Exporter version in the log traces
* Use UV as package manager for local development
* Cleanup the code and add unit tests
* All metrics are exported as Prometheus Gauge Metrics
* Document in the README.md how to mount Restic repository cache in a Docker volume
* Add warning in the README.md about remote Restic repository costs
* Update Docker Compose examples
* Update Grafana dashboard with new metrics
* Publish Docker image for architecture linux/riscv64
* Update Restic 0.18.1 (built with Go 1.24)
* Update Python 3.14 and dependencies
* Update base Docker image to Alpine 3.23
* Update GitHub Actions

## 1.7.0 (2025/02/15)

* Add libc6-compat library to support rclone in arm64
* Update Restic 0.17.3 (built with Go 1.22.12)
* Update Python dependencies
* Update base Docker image to Alpine 3.21

## 1.6.0 (2024/08/16)

* Fix lock count for latest versions of Restic
* Added INSECURE_TLS environment variable to skip TLS verification for self-signed certificates
* Update Restic 0.17.0 (built with Go 1.22.6)
* Update Python dependencies
* Update base Docker image to Alpine 3.20

## 1.5.0 (2024/01/20)

* Replaced RESTIC_REPO_URL, RESTIC_REPO_PASSWORD and RESTIC_REPO_PASSWORD_FILE environment variables with the Restic equivalents
* Add new label "snapshot_tags" in the list of tags separated by comma. The label "snapshot_tag" only contains the first tag
* Update Restic 0.16.3
* Update Python dependencies
* Update base Docker image to Alpine 3.19

## 1.4.0 (2023/10/14)

* Include metric label client_version. Resolves #5
* Update Grafana dashboard to include repository locks and client version
* Update Restic 0.16.0
* Update Python 3.12

## 1.3.0 (2023/07/30)

* Add new metric "restic_locks_total" with the number of repository locks
* Add new label "snapshot_paths" in the metrics with the backup paths
* Add NO_LOCKS env var to skip restic locks collection
* Add INCLUDE_PATHS env var to include the backup paths in the metrics
* Add Rclone instructions in the readme
* Update Restic 0.15.2
* Update Python dependencies
* Update base Docker image to Alpine 3.18

## 1.2.2 (2023/03/31)

* Include OpenSSH in the Docker image to support SFTP protocol

## 1.2.1 (2023/03/26)

* Improve hash calculation to avoid duplicate clients (snapshot_hash label changes)

## 1.2.0 (2023/03/18)

* Add new label "snapshot_tag" in the metrics with the backup tag (if tags is present)
* Add new metric "restic_scrape_duration_seconds"
* Add EXIT_ON_ERROR env var to control behaviour on error
* Add NO_CHECK env var to skip restic check stats
* Add NO_STATS env var to skip stats per backup
* Fix crash when backup username is empty. #7

## 1.1.0 (2023/02/02)

* Update Restic 0.15.1
* Update prometheus-client 0.16.0
* Fix snapshot time parsing for old versions of Restic. Resolves #1
* Exit if the repository password is not configured
* Improve error handling and better log traces
* Rename PASSWORD_FILE env var to RESTIC_REPO_PASSWORD_FILE
* Update Grafana dashboard
* Add documentation for other backends

## 1.0.0 (2022/12/06)

* First release
* Restic 0.14.0
