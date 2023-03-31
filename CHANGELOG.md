# Changelog

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
