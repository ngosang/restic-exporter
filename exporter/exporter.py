#!/usr/bin/env python
import datetime
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import traceback
from collections.abc import Iterable
from dataclasses import dataclass

from prometheus_client import Metric, start_http_server
from prometheus_client.core import REGISTRY, CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector


@dataclass
class ResticSnapshot:
    time: str
    hostname: str
    username: str
    paths: list[str]
    id: str
    short_id: str
    tags: list[str]
    program_version: str
    hash: str
    timestamp: float


@dataclass
class ResticStats:
    total_size: int
    total_file_count: int


@dataclass
class ResticClient:
    hostname: str
    username: str
    version: str
    snapshot_hash: str
    snapshot_tag: str
    snapshot_tags: str
    snapshot_paths: str
    timestamp: float
    size_total: int
    files_total: int
    snapshots_total: int


@dataclass
class ResticMetrics:
    check_success: int
    locks_total: int
    clients: list[ResticClient]
    snapshots_total: int
    duration: float


class ResticCollector(Collector):
    def __init__(
        self,
        disable_check: bool,
        disable_stats: bool,
        disable_locks: bool,
        include_paths: bool,
        insecure_tls: bool,
    ) -> None:
        self.disable_check = disable_check
        self.disable_stats = disable_stats
        self.disable_locks = disable_locks
        self.include_paths = include_paths
        self.insecure_tls = insecure_tls
        # todo: the stats cache increases over time -> remove old ids
        # todo: cold start -> the stats cache could be saved in a persistent volume
        # todo: cold start -> the restic cache (/root/.cache/restic) could be
        #   saved in a persistent volume
        self.stats_cache: dict[str, ResticStats] = {}
        self.metrics: ResticMetrics | None = None

    def collect(self) -> Iterable[Metric]:
        logging.debug("Incoming request")

        common_label_names: list[str] = [
            "client_hostname",
            "client_username",
            "client_version",
            "snapshot_hash",
            "snapshot_tag",
            "snapshot_tags",
            "snapshot_paths",
        ]

        check_success = GaugeMetricFamily(
            "restic_check_success",
            "Result of restic check operation in the repository",
            labels=[],
        )
        locks_total = CounterMetricFamily(
            "restic_locks_total",
            "Total number of locks in the repository",
            labels=[],
        )
        snapshots_total = CounterMetricFamily(
            "restic_snapshots_total",
            "Total number of snapshots in the repository",
            labels=[],
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
        scrape_duration_seconds = GaugeMetricFamily(
            "restic_scrape_duration_seconds",
            "Amount of time each scrape takes",
            labels=[],
        )

        check_success.add_metric([], self.metrics.check_success)
        locks_total.add_metric([], self.metrics.locks_total)
        snapshots_total.add_metric([], self.metrics.snapshots_total)

        for client in self.metrics.clients:
            common_label_values = [
                client.hostname,
                client.username,
                client.version,
                client.snapshot_hash,
                client.snapshot_tag,
                client.snapshot_tags,
                client.snapshot_paths,
            ]

            backup_timestamp.add_metric(common_label_values, client.timestamp)
            backup_files_total.add_metric(common_label_values, client.files_total)
            backup_size_total.add_metric(common_label_values, client.size_total)
            backup_snapshots_total.add_metric(common_label_values, client.snapshots_total)

        scrape_duration_seconds.add_metric([], self.metrics.duration)

        yield check_success
        yield locks_total
        yield snapshots_total
        yield backup_timestamp
        yield backup_files_total
        yield backup_size_total
        yield backup_snapshots_total
        yield scrape_duration_seconds

    def refresh(self, exit_on_error: bool = False) -> None:
        try:
            self.metrics = self.get_metrics()
        except Exception:
            logging.error(
                "Unable to collect metrics from Restic. %s",
                traceback.format_exc(0).replace("\n", " "),
            )

            # Shutdown exporter on any error
            if exit_on_error:
                sys.exit(1)

    def get_metrics(self) -> ResticMetrics:
        duration = time.time()

        # calc total number of snapshots per hash
        all_snapshots = self.get_snapshots()
        snap_total_counter: dict[str, int] = {}
        for snap in all_snapshots:
            if snap.hash not in snap_total_counter:
                snap_total_counter[snap.hash] = 1
            else:
                snap_total_counter[snap.hash] += 1

        # get the latest snapshot per hash
        latest_snapshots_dup = self.get_snapshots(only_latest=True)
        latest_snapshots: dict[str, ResticSnapshot] = {}
        for snap in latest_snapshots_dup:
            if snap.hash not in latest_snapshots or snap.timestamp > latest_snapshots[snap.hash].timestamp:
                latest_snapshots[snap.hash] = snap

        clients: list[ResticClient] = []
        for snap in list(latest_snapshots.values()):
            # collect stats for each snap only if enabled
            if self.disable_stats:
                # return zero as "no-stats" value
                stats = ResticStats(
                    total_size=-1,
                    total_file_count=-1,
                )
            else:
                stats = self.get_stats(snap.id)

            clients.append(
                ResticClient(
                    hostname=snap.hostname,
                    username=snap.username,
                    version=snap.program_version,
                    snapshot_hash=snap.hash,
                    snapshot_tag=snap.tags[0] if snap.tags else "",
                    snapshot_tags=",".join(snap.tags),
                    snapshot_paths=(",".join(snap.paths) if self.include_paths else ""),
                    timestamp=snap.timestamp,
                    size_total=stats.total_size,
                    files_total=stats.total_file_count,
                    snapshots_total=snap_total_counter[snap.hash],
                )
            )

        # todo: fix the commented code when the bug is fixed in restic
        #  https://github.com/restic/restic/issues/2126
        # stats = self.get_stats()

        if self.disable_check:
            # return 2 as "no-check" value
            check_success = 2
        else:
            check_success = self.get_check()

        if self.disable_locks:
            # return 0 as "no-locks" value
            locks_total = 0
        else:
            locks_total = self.get_locks()

        return ResticMetrics(
            check_success=check_success,
            locks_total=locks_total,
            clients=clients,
            snapshots_total=len(all_snapshots),
            duration=time.time() - duration,
        )

    def get_snapshots(self, only_latest: bool = False) -> list[ResticSnapshot]:
        cmd: list[str] = [
            "restic",
            "--no-lock",
            "snapshots",
            "--json",
        ]

        if only_latest:
            cmd.extend(["--latest", "1"])

        if self.insecure_tls:
            cmd.extend(["--insecure-tls"])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception("Error executing restic snapshot command: " + self.parse_stderr(result))
        snapshots_data: list[dict] = json.loads(result.stdout.decode("utf-8"))

        snapshots: list[ResticSnapshot] = []
        for snap_data in snapshots_data:
            snapshot_hash = self.calc_snapshot_hash(snap_data)
            snap_timestamp = self.calc_snapshot_timestamp(snap_data)
            snapshot = ResticSnapshot(
                time=snap_data["time"],
                hostname=snap_data["hostname"],
                username=snap_data.get("username", ""),
                paths=snap_data.get("paths", []),
                id=snap_data.get("id", ""),
                short_id=snap_data.get("short_id", ""),
                tags=snap_data.get("tags", []),
                program_version=snap_data.get("program_version", ""),
                hash=snapshot_hash,
                timestamp=snap_timestamp,
            )
            snapshots.append(snapshot)

        return snapshots

    def get_stats(self, snapshot_id: str) -> ResticStats:
        # This command is expensive in CPU/Memory (1-5 seconds),
        # and much more when snapshot_id=None (3 minutes) -> we avoid this call for now
        # https://github.com/restic/restic/issues/2126
        if snapshot_id in self.stats_cache:
            return self.stats_cache[snapshot_id]

        cmd = ["restic", "--no-lock", "stats", "--json", snapshot_id]

        if self.insecure_tls:
            cmd.extend(["--insecure-tls"])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception("Error executing restic stats command: " + self.parse_stderr(result))
        stats_dict = json.loads(result.stdout.decode("utf-8"))

        stats = ResticStats(
            total_size=stats_dict["total_size"],
            total_file_count=stats_dict["total_file_count"],
        )
        self.stats_cache[snapshot_id] = stats

        return stats

    def get_check(self) -> int:
        # This command takes 20 seconds or more, but it's required
        cmd = [
            "restic",
            "--no-lock",
            "check",
        ]

        if self.insecure_tls:
            cmd.extend(["--insecure-tls"])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            return 1  # ok
        else:
            logging.warning("Error checking the repository health. %s", self.parse_stderr(result))
            return 0  # error

    def get_locks(self) -> int:
        cmd: list[str] = [
            "restic",
            "--no-lock",
            "list",
            "locks",
        ]

        if self.insecure_tls:
            cmd.extend(["--insecure-tls"])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception("Error executing restic list locks command: " + self.parse_stderr(result))
        text_result: str = result.stdout.decode("utf-8")
        lock_counter: int = 0
        for line in text_result.split("\n"):
            if re.match("^[a-z0-9]+$", line):
                lock_counter += 1

        return lock_counter

    @staticmethod
    def calc_snapshot_hash(snapshot: dict) -> str:
        text = snapshot["hostname"] + snapshot.get("username", "") + ",".join(snapshot["paths"])
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def calc_snapshot_timestamp(snapshot: dict) -> float:
        time_parsed = re.sub(r"\.[^+-]+", "", snapshot["time"])
        if len(time_parsed) > 19:
            # restic 14: '2023-01-12T06:59:33.1576588+01:00' ->
            # '2023-01-12T06:59:33+01:00'
            time_format = "%Y-%m-%dT%H:%M:%S%z"
        else:
            # restic 12: '2023-02-01T14:14:19.30760523Z' ->
            # '2023-02-01T14:14:19'
            time_format = "%Y-%m-%dT%H:%M:%S"
        return time.mktime(datetime.datetime.strptime(time_parsed, time_format).timetuple())

    @staticmethod
    def parse_stderr(result: subprocess.CompletedProcess) -> str:
        return result.stderr.decode("utf-8").replace("\n", " ") + " Exit code: " + str(result.returncode)


def get_version() -> str:
    current_path = os.path.dirname(__file__)
    pyproject_path = os.path.join(current_path, "pyproject.toml")
    if not os.path.exists(pyproject_path):
        pyproject_path = os.path.join(current_path, "..", "pyproject.toml")
    try:
        with open(pyproject_path, "r") as f:
            content = f.read()
        match = re.search(r'version\s*=\s*"([^"]+)"', content)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "unknown"


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO")),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    version = get_version()
    logging.info("Starting Restic Prometheus Exporter v%s", version)
    logging.info("It could take a while if the repository is remote")

    if os.environ.get("RESTIC_REPOSITORY") is None:
        logging.error("The environment variable RESTIC_REPOSITORY is mandatory")
        sys.exit(1)

    if (
        os.environ.get("RESTIC_PASSWORD") is None
        and os.environ.get("RESTIC_PASSWORD_FILE") is None
        and os.environ.get("RESTIC_PASSWORD_COMMAND") is None
    ):
        logging.error(
            "One of the environment variables RESTIC_PASSWORD, RESTIC_PASSWORD_FILE or "
            "RESTIC_PASSWORD_COMMAND is mandatory"
        )
        sys.exit(1)

    exporter_address = os.environ.get("LISTEN_ADDRESS", "0.0.0.0")
    exporter_port = int(os.environ.get("LISTEN_PORT", 8001))
    exporter_refresh_interval = int(os.environ.get("REFRESH_INTERVAL", 60))
    exporter_exit_on_error = bool(os.environ.get("EXIT_ON_ERROR", False))
    exporter_disable_check = bool(os.environ.get("NO_CHECK", False))
    exporter_disable_stats = bool(os.environ.get("NO_STATS", False))
    exporter_disable_locks = bool(os.environ.get("NO_LOCKS", False))
    exporter_include_paths = bool(os.environ.get("INCLUDE_PATHS", False))
    exporter_insecure_tls = bool(os.environ.get("INSECURE_TLS", False))

    try:
        collector = ResticCollector(
            disable_check=exporter_disable_check,
            disable_stats=exporter_disable_stats,
            disable_locks=exporter_disable_locks,
            include_paths=exporter_include_paths,
            insecure_tls=exporter_insecure_tls,
        )
        collector.refresh(exit_on_error=exporter_exit_on_error)
        REGISTRY.register(collector)
        start_http_server(exporter_port, exporter_address)
        logging.info("Serving at http://%s:%d", exporter_address, exporter_port)

        while True:
            logging.info("Refreshing stats every %d seconds", exporter_refresh_interval)
            time.sleep(exporter_refresh_interval)
            collector.refresh()

    except KeyboardInterrupt:
        logging.info("\nInterrupted")
        exit(0)
