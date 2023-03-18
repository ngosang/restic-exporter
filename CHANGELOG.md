# Changelog

## next_release

* Added EXIT_ON_ERROR env var - now is possible to control exit_on_errors
behaviour
* Added NO_CHECK env var, now is possible not perform restic check operation
* Added NO_STATS env var, now is possible not collect per backup stats
* Added backup tag to the metric labels (if tags is present)

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
