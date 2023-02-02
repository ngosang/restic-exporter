# ngosang/restic-exporter

[![Latest release](https://img.shields.io/github/v/release/ngosang/restic-exporter)](https://github.com/ngosang/restic-exporter/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/ngosang/restic-exporter)](https://hub.docker.com/r/ngosang/restic-exporter/)
[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-yellow.svg)](https://www.paypal.com/paypalme/diegoheras0xff)
[![Donate Bitcoin](https://img.shields.io/badge/Donate-Bitcoin-f7931a.svg)](https://www.blockchain.com/btc/address/14EcPN47rWXkmFvjfohJx2rQxxoeBRJhej)
[![Donate Ethereum](https://img.shields.io/badge/Donate-Ethereum-8c8c8c.svg)](https://www.blockchain.com/eth/address/0x0D1549BbB00926BF3D92c1A8A58695e982f1BE2E)

Prometheus exporter for the [Restic](https://github.com/restic/restic) backup system.

## Install

### Form source code

Requirements:
 * Python 3
 * [prometheus-client](https://github.com/prometheus/client_python)

```bash
pip install -r /requirements.txt

export RESTIC_REPO_URL=/data
export RESTIC_REPO_PASSWORD_FILE=/restic_password_file
python restic-exporter.py
```

### Docker

Docker images are available in [GHCR](https://github.com/ngosang/restic-exporter/pkgs/container/restic-exporter) and [DockerHub](https://hub.docker.com/r/ngosang/restic-exporter).

```bash
docker pull ghcr.io/ngosang/restic-exporter
or
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
* linux/s390x

#### docker-compose

Compatible with docker-compose v2 schemas:

```yaml
---
version: '2.1'
services:
  restic-exporter:
    image: ngosang/restic-exporter
    container_name: restic-exporter
    environment:
      - TZ=Europe/Madrid
      - RESTIC_REPO_URL=/data
      - RESTIC_REPO_PASSWORD=<password_here>
      # - RESTIC_REPO_PASSWORD_FILE=</file_with_password_here>
      - REFRESH_INTERVAL=1800 # 30 min
    volumes:
      - /host_path/restic/data:/data
    ports:
      - "8001:8001"
    restart: unless-stopped
```

#### docker cli

```bash
docker run -d \
  --name=restic-exporter \
  -e TZ=Europe/Madrid \
  -e RESTIC_REPO_URL=/data \
  -e RESTIC_REPO_PASSWORD=<password_here> \
  -e REFRESH_INTERVAL=1800 \
  -p 8001:8001 \
  --restart unless-stopped \
  ngosang/restic-exporter
```

## Configuration

This Prometheus exporter is compatible with all [backends supported by Restic](https://restic.readthedocs.io/en/latest/030_preparing_a_new_repo.html).
Some of them need additional environment variables for the secrets.

All configuration is done with environment variables:

- `RESTIC_REPO_URL`: Restic repository URL. All backends are supported. Examples:
  * Local repository: `/data`
  * REST Server: `rest:http://user:password@127.0.0.1:8000/`
  * Amazon S3: `s3:s3.amazonaws.com/bucket_name`
  * Backblaze B2: `b2:bucketname:path/to/repo`

- `RESTIC_REPO_PASSWORD`: Restic repository password in plain text. This is only required if `RESTIC_REPO_PASSWORD_FILE` is not defined.
- `RESTIC_REPO_PASSWORD_FILE`: File with the Restic repository password in plain text. This is only required if `RESTIC_REPO_PASSWORD` is not defined. Remember to mount the Docker volume with the file.
- `AWS_ACCESS_KEY_ID`: (Optional) Required for Amazon S3, Minio and Wasabi backends.
- `AWS_SECRET_ACCESS_KEY`: (Optional) Required for Amazon S3, Minio and Wasabi backends.
- `B2_ACCOUNT_ID`: (Optional) Required for Backblaze B2 backend.
- `B2_ACCOUNT_KEY`: (Optional) Required for Backblaze B2 backend.
- `REFRESH_INTERVAL`: (Optional) Refresh interval for the metrics in seconds. Computing the metrics is a expensive task, keep this value as high as possible. Default 60
- `LISTEN_PORT`: (Optional) The address the exporter should listen on. The default is `8001`.
- `LISTEN_ADDRESS`: (Optional) The address the exporter should listen on. The default is to listen on all addresses.
- `LOG_LEVEL`: (Optional) Log level of the traces. The default is `INFO`.

## Exported metrics

```shell
# HELP restic_check_success Result of restic check operation in the repository
# TYPE restic_check_success gauge
restic_check_success 1.0
# HELP restic_snapshots_total Total number of snapshots in the repository
# TYPE restic_snapshots_total counter
restic_snapshots_total 1777.0
# HELP restic_backup_timestamp Timestamp of the last backup
# TYPE restic_backup_timestamp gauge
restic_backup_timestamp{client_hostname="PC-HOME-1",client_username="PC-HOME-1\\User-1",snapshot_hash="1911eb846f1642c327936915f1fad4e16190d0ab6b68e045294f5f0280a00ebe"} 1.669754009e+09
# HELP restic_backup_files_total Number of files in the backup
# TYPE restic_backup_files_total counter
restic_backup_files_total{client_hostname="PC-HOME-1",client_username="PC-HOME-1\\User-1",snapshot_hash="1911eb846f1642c327936915f1fad4e16190d0ab6b68e045294f5f0280a00ebe"} 19051.0
# HELP restic_backup_size_total Total size of backup in bytes
# TYPE restic_backup_size_total counter
restic_backup_size_total{client_hostname="PC-HOME-1",client_username="PC-HOME-1\\User-1",snapshot_hash="1911eb846f1642c327936915f1fad4e16190d0ab6b68e045294f5f0280a00ebe"} 4.1174838248e+010
# HELP restic_backup_snapshots_total Total number of snapshots
# TYPE restic_backup_snapshots_total counter
restic_backup_snapshots_total{client_hostname="PC-HOME-1",client_username="PC-HOME-1\\User-1",snapshot_hash="1911eb846f1642c327936915f1fad4e16190d0ab6b68e045294f5f0280a00ebe"} 106.0
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
