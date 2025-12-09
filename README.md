# ngosang/restic-exporter

[![Latest release](https://img.shields.io/github/v/release/ngosang/restic-exporter)](https://github.com/ngosang/restic-exporter/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/ngosang/restic-exporter)](https://hub.docker.com/r/ngosang/restic-exporter/)
[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-yellow.svg)](https://www.paypal.com/paypalme/diegoheras0xff)
[![Donate Bitcoin](https://img.shields.io/badge/Donate-Bitcoin-f7931a.svg)](https://www.blockchain.com/btc/address/14EcPN47rWXkmFvjfohJx2rQxxoeBRJhej)
[![Donate Ethereum](https://img.shields.io/badge/Donate-Ethereum-8c8c8c.svg)](https://www.blockchain.com/eth/address/0x0D1549BbB00926BF3D92c1A8A58695e982f1BE2E)

Prometheus exporter for the [Restic](https://github.com/restic/restic) backup system.

## Install

### From source code

Requirements:
* Python >= 3.12
* [Uv package manager](https://github.com/astral-sh/uv)

Install dependencies:
* `uv sync`

Run the exporter from the CLI:
```bash
export RESTIC_REPOSITORY=/data
export RESTIC_PASSWORD=restic_password
uv run exporter/exporter.py
```

Format the code:
* `uv run ruff format ./`
* `uv run ruff check --fix ./`

Run the tests:
* `uv run pytest ./`

### Docker

Docker images are available in [GHCR](https://github.com/ngosang/restic-exporter/pkgs/container/restic-exporter) and [DockerHub](https://hub.docker.com/r/ngosang/restic-exporter).

```bash
docker pull ghcr.io/ngosang/restic-exporter
# or
docker pull ngosang/restic-exporter
```

#### Supported Architectures

The architectures supported by this image are:

* linux/386
* linux/amd64
* linux/arm/v6
* linux/arm/v7
* linux/arm64/v8
* linux/ppc64le
* linux/riscv64
* linux/s390x

#### Docker Compose

NOTE: It is recommended to mount the `/root/.cache/restic` path as an external volume to speed up Restic Exporter
startup time and to reduce costs if your repository is remote. This path contains the Restic repository cache. 

```yaml
---
services:
  restic-exporter:
    image: ngosang/restic-exporter
    container_name: restic-exporter
    environment:
      - TZ=Europe/Madrid
      - RESTIC_REPOSITORY=/data
      - RESTIC_PASSWORD=<password_here>
      # - RESTIC_PASSWORD_FILE=<file_path_with_password_here>
      - REFRESH_INTERVAL=3600 # 1 hour
    volumes:
      - /host_path/restic/data:/data
      # - /host_path/restic/cache:/root/.cache/restic
    ports:
      - "8001:8001"
    restart: unless-stopped
```

#### Docker CLI

```bash
docker run -d \
  --name=restic-exporter \
  -e TZ=Europe/Madrid \
  -e RESTIC_REPOSITORY=/data \
  -e RESTIC_PASSWORD=<password_here> \
  -e REFRESH_INTERVAL=3600 \
  -p 8001:8001 \
  -v /host_path/restic/data:/data \
  --restart unless-stopped \
  ngosang/restic-exporter
```

## Configuration

This Prometheus exporter is compatible with all [backends supported by Restic](https://restic.readthedocs.io/en/latest/030_preparing_a_new_repo.html).
Some of them need additional environment variables for the secrets.

All configuration is done with environment variables:

- `RESTIC_REPOSITORY`: Restic repository URL. All backends are supported. Examples:
  * Local repository: `/data`
  * REST Server: `rest:http://user:password@127.0.0.1:8000/`
  * Amazon S3: `s3:s3.amazonaws.com/bucket_name`
  * Backblaze B2: `b2:bucketname:path/to/repo`
  * Rclone (see notes below): `rclone:gd-backup:/restic`

- Repository password configuration. Choose one of the following methods:
  - `RESTIC_PASSWORD`: Restic repository password in plain text.
  - `RESTIC_PASSWORD_FILE`: File with the Restic repository password in plain text. Remember to mount the Docker volume
with the file.
  - `RESTIC_PASSWORD_COMMAND`: Program to be called when the password is needed.

- `REFRESH_INTERVAL`: (Optional) Refresh interval for the metrics in seconds. Computing the metrics is an expensive
task, keep this value as high as possible. Default is `3600` seconds (1 hour).
  - **WARNING**: With default settings, downloading from remote repositories may be costly if using this exporter with
a remote Cloud-based restic repository (e.g. GCP GCS, Amazon S3). This may cause a surprisingly high spike in your
infrastructure costs (e.g. for small restic repositories that don't download frequently, this may increase your costs
by multiple orders of magnitude). Consider setting `REFRESH_INTERVAL` to considerably higher values (e.g. `86400` for
once per day) to lower this impact.
- `LISTEN_PORT`: (Optional) The address the exporter should listen on. The default is `8001`.
- `LISTEN_ADDRESS`: (Optional) The address the exporter should listen on. The default is to listen on all addresses.
- `LOG_LEVEL`: (Optional) Log level of the traces. The default is `INFO`.
- `EXIT_ON_ERROR`: (Optional) Shutdown exporter on any `restic` error. Default is `Flase` (only log error, such as
network error with Cloud backends).
- `NO_CHECK`: (Optional) Do not perform `restic check` operation for performance reasons. Default is `False` (perform
`restic check`).
- `NO_GLOBAL_STATS`: (Optional) Do not perform `restic stats` operation for performance reasons. Default is `False` (perform
`restic stats`).
- `NO_LEGACY_STATS`: (Optional) Do not collect per backup statistics for performance reasons. Default is `False` (collect per
backup statistics).
  - **NOTE**: Since Restic 0.17 getting the statistics is much faster and it is always enabled. This configuration only
applies for backups performed with an old version of the Restic client.
- `NO_LOCKS`: (Optional) Do not collect the number of locks. Default is `False` (collect the number of locks).
- `INCLUDE_PATHS`: (Optional) Include snapshot paths for each backup. The paths are separated by commas. Default is
`False` (not collect the paths).
- `INSECURE_TLS`: (Optional) skip TLS verification for self-signed certificates. Default is `False` (not skip).
- `AWS_ACCESS_KEY_ID`: (Optional) Required for Amazon S3, Minio and Wasabi backends.
- `AWS_SECRET_ACCESS_KEY`: (Optional) Required for Amazon S3, Minio and Wasabi backends.
- `B2_ACCOUNT_ID`: (Optional) Required for Backblaze B2 backend.
- `B2_ACCOUNT_KEY`: (Optional) Required for Backblaze B2 backend.

### Configuration for Rclone

Rclone is not included in the Docker image. You have to mount the Rclone executable and the Rclone configuration from
the host machine. Here is an example with docker-compose:

```yaml
services:
  restic-exporter:
    image: ngosang/restic-exporter
    container_name: restic-exporter
    environment:
      - TZ=Europe/Madrid
      - RESTIC_REPOSITORY=rclone:gd-backup:/restic
      - RESTIC_PASSWORD= 
      - REFRESH_INTERVAL=3600 # 1 hour
    volumes:
      - /host_path/restic/data:/data
      # - /host_path/restic/cache:/root/.cache/restic
      - /usr/bin/rclone:/usr/bin/rclone:ro
      - /host_path/restic/rclone.conf:/root/.config/rclone/rclone.conf:ro
    ports:
      - "8001:8001"
    restart: unless-stopped
```

## Exported metrics

```bash
# HELP restic_check_success Result of restic check operation in the repository
restic_check_success 1.0
# HELP restic_locks_total Total number of locks in the repository
restic_locks_total 0.0
# HELP restic_scrape_duration_seconds Amount of time each scrape takes
restic_scrape_duration_seconds 87.033
# HELP restic_size_total Total size of the repository in bytes
restic_size_total 38573452
# HELP restic_uncompressed_size_total Total uncompressed size of the repository in bytes
restic_uncompressed_size_total 44077773
# HELP restic_compression_ratio Compression ratio of the repository
restic_compression_ratio 1.142
# HELP restic_blob_count_total Total number of blobs in the repository
restic_blob_count_total 1500
# HELP restic_snapshots_total Total number of snapshots in the repository
restic_snapshots_total 100.0
# HELP restic_backup_timestamp Timestamp of the last backup
restic_backup_timestamp{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 1.666273638e+09
# HELP restic_backup_snapshots_total Total number of snapshots
restic_backup_snapshots_total{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 1.0
# HELP restic_backup_files_total Number of files in the backup
restic_backup_files_total{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 8.0
# HELP restic_backup_size_total Total size of backup in bytes
restic_backup_size_total{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 4.3309562e+07
# HELP restic_backup_files_new Number of new files in the backup
restic_backup_files_new{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 2280.0
# HELP restic_backup_files_changed Number of changed files in the backup
restic_backup_files_changed{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 3167.0
# HELP restic_backup_files_unmodified Number of unmodified files in the backup
restic_backup_files_unmodified{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 239163.0
# HELP restic_backup_dirs_new Number of new directories in the backup
restic_backup_dirs_new{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 1.0
# HELP restic_backup_dirs_changed Number of changed directories in the backup
restic_backup_dirs_changed{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 255.0
# HELP restic_backup_dirs_unmodified Number of unmodified directories in the backup
restic_backup_dirs_unmodified{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 53499.0
# HELP restic_backup_data_added_bytes Number of bytes added in the backup
restic_backup_data_added_bytes{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 5.29759957e+08
# HELP restic_backup_duration_seconds Amount of time Restic took to make the backup
restic_backup_duration_seconds{client_hostname="example",client_username="root",client_version="restic 0.18.1",snapshot_hash="785c44996fa586ccf634fb0b45cd50d3afe8556ad44476bc5c3372bcdfbae4cd",snapshot_tag="mysql",snapshot_tags="mysql,tag2",snapshot_paths="/mysql/data,/mysql/config"} 33.165685
```

## Prometheus config

Example Prometheus configuration:

```yaml
scrape_configs:
  - job_name: 'restic-exporter'
    static_configs:
      - targets: ['192.168.1.100:8001']
```

## Prometheus / Alertmanager rules

Example Prometheus rules for alerting:

```yaml
  - alert: ResticCheckFailed
    expr: restic_check_success == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: Restic check failed (instance {{ $labels.instance }})
      description: Restic check failed\n  VALUE = {{ $value }}\n  LABELS = {{ $labels }}

  - alert: ResticOutdatedBackup
    # 1209600 = 15 days
    expr: time() - restic_backup_timestamp > 1209600
    for: 0m
    labels:
      severity: critical
    annotations:
      summary: Restic {{ $labels.client_hostname }} / {{ $labels.client_username }} backup is outdated
      description: Restic backup is outdated\n  VALUE = {{ $value }}\n  LABELS = {{ $labels }}
```

## Grafana dashboard

There is a reference Grafana dashboard in [grafana/grafana_dashboard.json](./grafana/grafana_dashboard.json).

![](./grafana/grafana_dashboard.png)
