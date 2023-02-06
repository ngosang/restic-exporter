#!/usr/bin/env python3
import datetime
import hashlib
import json
import logging
import os
import time
import re
import subprocess
import sys
import traceback

import prometheus_client
import prometheus_client.core


class ResticCollector(object):
    def __init__(self, repository, password_file):
        self.repository = repository
        self.password_file = password_file
        # todo: the stats cache increases over time -> remove old ids
        # todo: cold start -> the stats cache could be saved in a persistent volume
        # todo: cold start -> the restic cache (/root/.cache/restic) could be saved in a persistent volume
        self.stats_cache = {}
        self.metrics = {}
        self.refresh(True)

    def collect(self):
        logging.debug("Incoming request")

        common_label_names = [
            "client_hostname",
            "client_username",
            "snapshot_hash"
        ]

        check_success = prometheus_client.core.GaugeMetricFamily(
            "restic_check_success",
            "Result of restic check operation in the repository",
            labels=[])

        snapshots_total = prometheus_client.core.CounterMetricFamily(
            "restic_snapshots_total",
            "Total number of snapshots in the repository",
            labels=[])

        backup_timestamp = prometheus_client.core.GaugeMetricFamily(
            "restic_backup_timestamp",
            "Timestamp of the last backup",
            labels=common_label_names)

        backup_files_total = prometheus_client.core.CounterMetricFamily(
            "restic_backup_files_total",
            "Number of files in the backup",
            labels=common_label_names)

        backup_size_total = prometheus_client.core.CounterMetricFamily(
            "restic_backup_size_total",
            "Total size of backup in bytes",
            labels=common_label_names)

        backup_snapshots_total = prometheus_client.core.CounterMetricFamily(
            "restic_backup_snapshots_total",
            "Total number of snapshots",
            labels=common_label_names)

        check_success.add_metric([], self.metrics["check_success"])
        snapshots_total.add_metric([], self.metrics["snapshots_total"])

        for client in self.metrics['clients']:
            common_label_values = [
                client["hostname"],
                client["username"],
                client["snapshot_hash"]
            ]
            backup_timestamp.add_metric(common_label_values, client["timestamp"])
            backup_files_total.add_metric(common_label_values, client["files_total"])
            backup_size_total.add_metric(common_label_values, client["size_total"])
            backup_snapshots_total.add_metric(common_label_values, client["snapshots_total"])

        yield check_success
        yield snapshots_total
        yield backup_timestamp
        yield backup_files_total
        yield backup_size_total
        yield backup_snapshots_total

    def refresh(self, exit_on_error=False):
        try:
            self.metrics = self.get_metrics()
        except Exception:
            logging.error("Unable to collect metrics from Restic. %s", traceback.format_exc(0).replace("\n", " "))
            if exit_on_error:
                sys.exit(1)

    def get_metrics(self):
        all_snapshots = self.get_snapshots()
        latest_snapshots = self.get_snapshots(True)
        clients = []
        for snap in latest_snapshots:
            stats = self.get_stats(snap['id'])

            time_parsed = re.sub(r'\.[^+-]+', '', snap['time'])
            if len(time_parsed) > 19:
                # restic 14: '2023-01-12T06:59:33.1576588+01:00' -> '2023-01-12T06:59:33+01:00'
                time_format = "%Y-%m-%dT%H:%M:%S%z"
            else:
                # restic 12: '2023-02-01T14:14:19.30760523Z' -> '2023-02-01T14:14:19'
                time_format = "%Y-%m-%dT%H:%M:%S"
            timestamp = time.mktime(datetime.datetime.strptime(time_parsed, time_format).timetuple())

            snapshots_total = 0
            for snap2 in all_snapshots:
                if snap2['hash'] == snap['hash']:
                    snapshots_total += 1

            clients.append({
                'snapshot_hash': snap['hash'],
                'hostname': snap['hostname'],
                'username': snap['username'] if 'username' in snap else '',
                'timestamp': timestamp,
                'size_total': stats['total_size'],
                'files_total': stats['total_file_count'],
                'snapshots_total': snapshots_total
            })
        # todo: fix the commented code when the bug is fixed in restic
        #  https://github.com/restic/restic/issues/2126
        # stats = self.get_stats()
        check_success = self.get_check()
        metrics = {
            'check_success': check_success,
            'clients': clients,
            # 'size_total': stats['total_size'],
            # 'files_total': stats['total_file_count'],
            'snapshots_total': len(all_snapshots)
        }
        return metrics

    def get_snapshots(self, only_latest=False):
        cmd = [
            'restic',
            '-r', self.repository,
            '-p', self.password_file,
            '--no-lock',
            'snapshots', '--json'
        ]
        if only_latest:
            cmd.extend(['--latest', '1'])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception("Error executing restic snapshot command. " + self.parse_stderr(result))
        snapshots = json.loads(result.stdout.decode('utf-8'))
        for snap in snapshots:
            snap['hash'] = self.calc_snapshot_hash(snap)
        return snapshots

    def get_stats(self, snapshot_id=None):
        # This command is expensive in CPU/Memory (1-5 seconds),
        # and much more when snapshot_id=None (3 minutes) -> we avoid this call for now
        # https://github.com/restic/restic/issues/2126
        if snapshot_id is not None and snapshot_id in self.stats_cache:
            return self.stats_cache[snapshot_id]

        cmd = [
            'restic',
            '-r', self.repository,
            '-p', self.password_file,
            '--no-lock',
            'stats', '--json'
        ]
        if snapshot_id is not None:
            cmd.extend([snapshot_id])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception("Error executing restic stats command. " + self.parse_stderr(result))
        stats = json.loads(result.stdout.decode('utf-8'))

        if snapshot_id is not None:
            self.stats_cache[snapshot_id] = stats

        return stats

    def get_check(self):
        # This command takes 20 seconds or more, but it's required
        cmd = [
            'restic',
            '-r', self.repository,
            '-p', self.password_file,
            '--no-lock',
            'check'
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            return 1  # ok
        logging.warning("Error checking the repository health. " + self.parse_stderr(result))
        return 0  # error

    def calc_snapshot_hash(self, snapshot: dict) -> str:
        text = snapshot['hostname'] + ",".join(snapshot['paths'])
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def parse_stderr(self, result):
        return result.stderr.decode('utf-8').replace("\n", " ") + " Exit code: " + str(result.returncode)


if __name__ == "__main__":
    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s',
        level=logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO")),
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info("Starting Restic Prometheus Exporter ...")
    logging.info("It could take a while if the repository is remote.")

    try:
        restic_repo_url = os.environ["RESTIC_REPO_URL"]
    except Exception:
        logging.error("Configuration error. The environment variable RESTIC_REPO_URL is mandatory")
        sys.exit(1)

    try:
        restic_repo_password_file = os.environ["RESTIC_REPO_PASSWORD_FILE"]
    except Exception:
        logging.error("Configuration error. The environment variable RESTIC_REPO_PASSWORD_FILE is mandatory")
        sys.exit(1)

    exporter_address = os.environ.get("LISTEN_ADDRESS", "0.0.0.0")
    exporter_port = int(os.environ.get("LISTEN_PORT", 8001))
    exporter_refresh_interval = int(os.environ.get("REFRESH_INTERVAL", 60))

    collector = ResticCollector(restic_repo_url, restic_repo_password_file)

    prometheus_client.core.REGISTRY.register(collector)
    prometheus_client.start_http_server(exporter_port, exporter_address)

    logging.info("Server listening in http://%s:%d/metrics", exporter_address, exporter_port)
    while True:
        logging.info("Refreshing stats every %d seconds", exporter_refresh_interval)
        time.sleep(exporter_refresh_interval)
        collector.refresh()
