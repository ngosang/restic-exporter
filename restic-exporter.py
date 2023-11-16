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

from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY


class ResticCollector(object):
    def __init__(self, repository, password_file_path, storage_boxes, **kwargs):
        # required stuff - repository, path to password file,
        # list of storageboxes where repository for hostis placed
        self.repository = repository
        self.password_file_path = password_file_path
        self.storage_boxes = storage_boxes
        self.repository_name = kwargs.get('repository_name', 'default')

        # exporter config
        self.exit_on_error = kwargs.get('exit_on_error', False)
        self.disable_check = kwargs.get('disable_check', False)
        self.disable_stats = kwargs.get('disable_stats', False)
        self.disable_locks = kwargs.get('disable_locks', False)
        self.include_paths = kwargs.get('include_paths', False)

        # restic executable config
        self.rclone_program = kwargs.get('rclone_program')
        self.filter_hosts = kwargs.get('filter_hosts')

        # todo: the stats cache increases over time -> remove old ids
        # todo: cold start -> the stats cache could be saved in a persistent volume

        self.stats_cache = {}
        self.metrics = {}
        self.refresh(self.exit_on_error)

    def get_base_cmd(self, storagebox=None):
        pwd_file_path = self.password_file_path if not storagebox \
            else os.path.join(self.password_file_path, str(storagebox))

        cmd = [
            "restic",
            "-r",
            self.repository,
            "-p",
            pwd_file_path
        ]

        if self.rclone_program:
            if storagebox:
                cmd.extend(['-o', f'rclone.program={self.rclone_program} storagebox.{storagebox}'])
            else:
                cmd.extend(['-o', f'rclone.program={self.rclone_program}'])

        return cmd

    def collect(self):
        logging.debug("Incoming request")

        common_host_labels = [
            "storagebox",
            "repository",
        ]

        common_label_names = [
            "client_hostname",
            "client_username",
            "client_version",
            "snapshot_hash",
            "snapshot_tag",
            "snapshot_paths",
        ]

        per_tag_label_names = [
            "snapshot_tag"
        ]

        all_snapshot_labels = [
            "snapshot_id",
            "snapshot_tag",
            "snapshot_timestamp",
        ]

        all_snapshot_labels.extend(common_host_labels)

        # add common host labels to per_tag_label_names and common_label_names
        common_label_names.extend(common_host_labels)
        per_tag_label_names.extend(common_host_labels)

        check_success = GaugeMetricFamily(
            "restic_check_success",
            "Result of restic check operation in the repository",
            labels=common_host_labels,
        )
        locks_total = CounterMetricFamily(
            "restic_locks_total",
            "Total number of locks in the repository",
            labels=common_host_labels,
        )
        snapshots_total = CounterMetricFamily(
            "restic_snapshots_total",
            "Total number of snapshots in the repository",
            labels=common_host_labels,
        )
        backup_timestamp = GaugeMetricFamily(
            "restic_backup_timestamp",
            "Timestamp of the last backup",
            labels=common_label_names,
        )
        backup_files_total = CounterMetricFamily(
            "restic_backup_files_total",
            "Number of files in the backup",
            labels=common_label_names,
        )
        backup_size_total = CounterMetricFamily(
            "restic_backup_size_total",
            "Total size of backup in bytes",
            labels=common_label_names,
        )
        backup_snapshots_total = CounterMetricFamily(
            "restic_backup_snapshots_total",
            "Total number of snapshots",
            labels=common_label_names,
        )
        backup_snapshots_by_type = GaugeMetricFamily(
            "restic_backup_snapshots_by_type",
            "Total number of snapshots by type",
            labels=per_tag_label_names,
        )
        scrape_duration_seconds = GaugeMetricFamily(
            "restic_scrape_duration_seconds",
            "Amount of time each scrape takes",
            labels=common_host_labels,
        )

        snapshot_size = GaugeMetricFamily(
            "restic_snapshot_size",
            "Size of snapshot in bytes",
            labels=all_snapshot_labels,
        )

        snapshot_files_count = GaugeMetricFamily(
            "restic_snapshot_files_count",
            "Number of files in snapshot",
            labels=all_snapshot_labels,
        )

        for metric in self.metrics:
            common_host_label_values = [
                metric["storagebox"],
                metric["repository"],
            ]

            check_success.add_metric(common_host_label_values, metric["check_success"])
            locks_total.add_metric(common_host_label_values, metric["locks_total"])
            snapshots_total.add_metric(common_host_label_values, metric["snapshots_total"])

            for tag, count in metric["snapshots_by_type"].items():
                by_type_label_values = [
                    tag,
                ]

                by_type_label_values.extend(common_host_label_values)

                backup_snapshots_by_type.add_metric(by_type_label_values, count)

            for snapshot_id, snapshot in metric["snapshots_stats"].items():
                snapshot_label_values = [
                    snapshot_id,
                    snapshot["snapshot_tag"],
                    snapshot["snapshot_timestamp"],
                ]

                snapshot_label_values.extend(common_host_label_values)

                snapshot_size.add_metric(snapshot_label_values, snapshot["total_size"])
                snapshot_files_count.add_metric(snapshot_label_values, snapshot["total_file_count"])

            for client in metric["clients"]:
                common_label_values = [
                    client["hostname"],
                    client["username"],
                    client["version"],
                    client["snapshot_hash"],
                    client["snapshot_tag"],
                    client["snapshot_paths"],
                ]

                common_label_values.extend(common_host_label_values)

                backup_timestamp.add_metric(common_label_values, client["timestamp"])
                backup_files_total.add_metric(common_label_values, client["files_total"])
                backup_size_total.add_metric(common_label_values, client["size_total"])
                backup_snapshots_total.add_metric(
                    common_label_values, client["snapshots_total"]
                )

            scrape_duration_seconds.add_metric([], metric["duration"])

            yield check_success
            yield locks_total
            yield snapshots_total
            yield backup_timestamp
            yield backup_files_total
            yield backup_size_total
            yield backup_snapshots_total
            yield backup_snapshots_by_type
            yield snapshot_size
            yield snapshot_files_count
            yield scrape_duration_seconds

    def refresh(self, exit_on_error=False):
        try:
            self.metrics = self.get_metrics()
        except Exception:
            logging.error(
                "Unable to collect metrics from Restic. %s",
                traceback.format_exc(),
            )

            # Shutdown exporter for any error
            if exit_on_error:
                sys.exit(1)

    def get_metrics(self):
        start = time.time()

        if self.storage_boxes:
            metrics = []
            for storagebox in self.storage_boxes:
                metrics.append(self.get_storagebox_metrics(storagebox))

        else:
            metrics = [self.get_repo_metrics()]

        return metrics

    def _parse_metrics(self, storagebox: str = None):
        start_time = time.time()

        all_snapshots = self.get_snapshots(storagebox)

        snap_total_counter = {}
        snap_by_type_total_counter = {}
        snapshot_stats = {}
        for snap in all_snapshots:
            # get total number of matching snapshots
            if snap["hash"] not in snap_total_counter:
                snap_total_counter[snap["hash"]] = 1
            else:
                snap_total_counter[snap["hash"]] += 1

            # count snapshots by type
            for tag in snap.get("tags", []):
                if tag not in snap_by_type_total_counter:
                    snap_by_type_total_counter[tag] = 1
                else:
                    snap_by_type_total_counter[tag] += 1

            # create stats entry for all snapshots
            snap_stats = self.get_stats(storagebox=storagebox, snapshot_id=snap["id"])
            snapshot_stats[snap["id"]] = {
                "snapshot_tag": snap["tags"][0],
                "snapshot_timestamp": snap["time"],
                "total_size": snap_stats.get('total_size', 0),
                "total_file_count": snap_stats.get('total_file_count', 0),
            }

        latest_snapshots_dup = self.get_snapshots(storagebox, True)
        latest_snapshots = {}
        for snap in latest_snapshots_dup:
            time_parsed = re.sub(r"\.[^+-]+", "", snap["time"])
            if len(time_parsed) > 19:
                # restic 14: '2023-01-12T06:59:33.1576588+01:00' ->
                # '2023-01-12T06:59:33+01:00'
                time_format = "%Y-%m-%dT%H:%M:%S%z"
            else:
                # restic 12: '2023-02-01T14:14:19.30760523Z' ->
                # '2023-02-01T14:14:19'
                time_format = "%Y-%m-%dT%H:%M:%S"
                timestamp = time.mktime(
                    datetime.datetime.strptime(time_parsed, time_format).timetuple()
                )

                snap["timestamp"] = timestamp
                if snap["hash"] not in latest_snapshots or \
                    snap["timestamp"] > latest_snapshots[snap["hash"]]["timestamp"]:
                        latest_snapshots[snap["hash"]] = snap

        clients = []
        for snap in list(latest_snapshots.values()):
            # collect stats for each snap only if enabled
            if self.disable_stats:
                # return zero as "no-stats" value
                stats = {
                    "total_size": -1,
                    "total_file_count": -1,
                }
            else:
                stats = self.get_stats(storagebox=storagebox, snapshot_id=snap["id"])
                clients.append(
                    {
                        "storagebox": storagebox,
                        "repository": self.repository_name,
                        "hostname": snap["hostname"],
                        "username": snap["username"],
                        "version": snap["program_version"] if "program_version" in snap else "",
                        "snapshot_hash": snap["hash"],
                        "snapshot_tag": snap["tags"][0] if "tags" in snap else "",
                        "snapshot_paths": ",".join(snap["paths"]) if self.include_paths else "",
                        "timestamp": snap["timestamp"],
                        "size_total": stats["total_size"],
                        "files_total": stats["total_file_count"],
                        "snapshots_total": snap_total_counter[snap["hash"]],
                    }
                )

        # todo: fix the commented code when the bug is fixed in restic
        #  https://github.com/restic/restic/issues/2126
        # stats = self.get_stats()

        if self.disable_check:
            # return 2 as "no-check" value
            check_success = 2
        else:
            check_success = self.get_check(storagebox)

        if self.disable_locks:
            # return 0 as "no-locks" value
            locks_total = 0
        else:
            locks_total = self.get_locks(storagebox)

        metrics = {
            "snapshots_by_type": snap_by_type_total_counter,
            "snapshots_stats": snapshot_stats,
            "check_success": check_success,
            "locks_total": locks_total,
            "clients": clients,
            "snapshots_total": len(all_snapshots),
            "duration": time.time() - start_time,
            "storagebox": storagebox,
            "repository": self.repository_name,
            # 'size_total': stats['total_size'],
            # 'files_total': stats['total_file_count'],
        }

        return metrics

    def get_storagebox_metrics(self, storagebox):
        return self._parse_metrics(storagebox)

    def get_repo_metrics(self):
        return self._parse_metrics()

    def get_snapshots(self, storagebox=None, only_latest=False):
        cmd = self.get_base_cmd(storagebox)

        cmd.extend([
            "--no-lock",
            "snapshots",
            "--json",
        ])

        if self.filter_hosts:
            cmd.extend(['--host', self.filter_hosts])

        # TODO: Fetch total snapshots by tag
        # TODO: Fetch latest snapshot by tag
        # TODO: implement count of snapshots by tag and compare with retention policy
        if only_latest:
            cmd.extend(["--latest", "1"])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode != 0:
            raise Exception(
                "Error executing restic snapshot command: " + self.parse_stderr(result)
            )

        snapshots = json.loads(result.stdout.decode("utf-8"))

        for snap in snapshots:
            if "username" not in snap:
                snap["username"] = ""

            snap["hash"] = self.calc_snapshot_hash(snap)

        return snapshots

    def get_stats(self, storagebox=None, snapshot_id=None):
        # This command is expensive in CPU/Memory (1-5 seconds),
        # and much more when snapshot_id=None (3 minutes) -> we avoid this call for now
        # https://github.com/restic/restic/issues/2126
        if snapshot_id is not None and snapshot_id in self.stats_cache:
            return self.stats_cache[snapshot_id]

        cmd = self.get_base_cmd(storagebox)

        cmd.extend([
            "--no-lock",
            "stats",
            "--json",
        ])

        if self.filter_hosts:
            cmd.extend(['--host', self.filter_hosts])

        if snapshot_id is not None:
            cmd.extend([snapshot_id])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception(
                "Error executing restic stats command: " + self.parse_stderr(result)
            )
        stats = json.loads(result.stdout.decode("utf-8"))

        if snapshot_id is not None:
            self.stats_cache[snapshot_id] = stats

        return stats

    def get_check(self, storagebox=None):
        # This command takes 20 seconds or more, but it's required
        cmd = self.get_base_cmd(storagebox)

        cmd.extend([
            "--no-lock",
            "check",
        ])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            return 1  # ok
        else:
            logging.warning(
                "Error checking the repository health. " + self.parse_stderr(result)
            )
            return 0  # error

    def get_locks(self, storagebox=None):
        cmd = self.get_base_cmd(storagebox)

        cmd.extend([
            "list",
            "locks",
        ])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception(
                "Error executing restic list locks command: " + self.parse_stderr(result)
            )
        text_result = result.stdout.decode("utf-8")
        return len(text_result.split("\n")) - 1

    @staticmethod
    def calc_snapshot_hash(snapshot: dict) -> str:
        text = snapshot["hostname"] + snapshot["username"] + ",".join(snapshot["paths"])
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def parse_stderr(result):
        return (
                result.stderr.decode("utf-8").replace("\n", " ")
                + " Exit code: "
                + str(result.returncode)
        )


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO")),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.info("Starting Restic Prometheus Exporter")
    logging.info("It could take a while if the repository is remote")

    repository = None
    password_file = None
    storageboxes = None

    try:
        repository = os.environ.get('RESTIC_REPOSITORY', None)

        if not repository:
            raise Exception("RESTIC_REPOSITORY is required")

        password_file = os.environ.get("RESTIC_REPO_PASSWORD_FILE", None)

        if not password_file:
            raise Exception("RESTIC_REPO_PASSWORD_FILE is required")

        storageboxes = os.environ.get("RESTIC_STORAGEBOXES", None)

        if storageboxes:
            storageboxes = storageboxes.split(',')

    except Exception as e:
        logging.error(e)
        sys.exit(1)

    # exporter config
    exporter_address = os.environ.get("LISTEN_ADDRESS", "0.0.0.0")
    exporter_port = int(os.environ.get("LISTEN_PORT", 8001))
    exporter_refresh_interval = int(os.environ.get("REFRESH_INTERVAL", 60))
    exporter_exit_on_error = bool(os.environ.get("EXIT_ON_ERROR", False))
    exporter_disable_check = bool(os.environ.get("NO_CHECK", False))
    exporter_disable_stats = bool(os.environ.get("NO_STATS", False))
    exporter_disable_locks = bool(os.environ.get("NO_LOCKS", False))
    exporter_include_paths = bool(os.environ.get("INCLUDE_PATHS", False))

    # rclone config
    rclone_program = os.environ.get('RCLONE_PROGRAM', None)

    # restic config
    filter_hosts = os.environ.get('RESTIC_FILTER_HOSTS', None)
    retention_policy = os.environ.get('RESTIC_RETENTION_POLICY', None)

    # repository info
    repository_name = os.environ.get('RESTIC_REPOSITORY_NAME', 'default')

    # TODO: counts based on restic_retention_policy

    try:
        collector = ResticCollector(
            repository,
            password_file,
            storageboxes,
            # rclone and restic params
            rclone_program=rclone_program,
            filter_hosts=filter_hosts,
            restic_retention_policy=retention_policy,
            repository_name=repository_name,
            # exporter params
            exit_on_error=exporter_exit_on_error,
            disable_checks=exporter_disable_check,
            disable_stats=exporter_disable_stats,
            disable_locks=exporter_disable_locks,
            include_paths=exporter_include_paths,
        )
        REGISTRY.register(collector)
        start_http_server(exporter_port, exporter_address)
        logging.info(
            "Serving at http://{0}:{1}".format(exporter_address, exporter_port)
        )

        while True:
            logging.info(
                "Refreshing stats every {0} seconds".format(exporter_refresh_interval)
            )
            time.sleep(exporter_refresh_interval)
            collector.refresh()

    except KeyboardInterrupt:
        logging.info("\nInterrupted")
        exit(0)
