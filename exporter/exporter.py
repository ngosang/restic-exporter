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
from prometheus_client.core import REGISTRY, GaugeMetricFamily
from prometheus_client.registry import Collector


@dataclass
class ResticGlobalStats:
    total_size: int
    total_uncompressed_size: int
    compression_ratio: float
    total_blob_count: int
    total_snapshots_count: int


@dataclass
class ResticStats:
    # from restic stats and from snapshot summary
    total_size: int
    total_file_count: int
    # from snapshot summary
    files_new: int
    files_changed: int
    files_unmodified: int
    dirs_new: int
    dirs_changed: int
    dirs_unmodified: int
    data_added: int
    duration: float


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
    stats: ResticStats | None


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
    snapshots_total: int
    stats: ResticStats


@dataclass
class ResticMetrics:
    check_success: int
    locks_total: int
    clients: list[ResticClient]
    duration: float
    global_stats: ResticGlobalStats


class ResticCollector(Collector):
    def __init__(
        self,
        disable_check: bool,
        disable_global_stats: bool,
        disable_legacy_stats: bool,
        disable_locks: bool,
        include_paths: bool,
        insecure_tls: bool,
    ) -> None:
        self.disable_check = disable_check
        self.disable_global_stats = disable_global_stats
        self.disable_legacy_stats = disable_legacy_stats
        self.disable_locks = disable_locks
        self.include_paths = include_paths
        self.insecure_tls = insecure_tls
        self.stats_snapshot_cache: dict[str, ResticStats] = {}
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

        # global metrics
        check_success = GaugeMetricFamily(
            "restic_check_success",
            "Result of restic check operation in the repository",
            labels=[],
        )
        locks_total = GaugeMetricFamily(
            "restic_locks_total",
            "Total number of locks in the repository",
            labels=[],
        )
        scrape_duration_seconds = GaugeMetricFamily(
            "restic_scrape_duration_seconds",
            "Amount of time each scrape takes",
            labels=[],
        )
        size_total = GaugeMetricFamily(
            "restic_size_total",
            "Total size of the repository in bytes",
            labels=[],
        )
        uncompressed_size_total = GaugeMetricFamily(
            "restic_uncompressed_size_total",
            "Total uncompressed size of the repository in bytes",
            labels=[],
        )
        compression_ratio = GaugeMetricFamily(
            "restic_compression_ratio",
            "Compression ratio of the repository",
            labels=[],
        )
        blob_count_total = GaugeMetricFamily(
            "restic_blob_count_total",
            "Total number of blobs in the repository",
            labels=[],
        )
        snapshots_total = GaugeMetricFamily(
            "restic_snapshots_total",
            "Total number of snapshots in the repository",
            labels=[],
        )
        # per backup metrics
        backup_timestamp = GaugeMetricFamily(
            "restic_backup_timestamp",
            "Timestamp of the last backup",
            labels=common_label_names,
        )
        backup_snapshots_total = GaugeMetricFamily(
            "restic_backup_snapshots_total",
            "Total number of snapshots",
            labels=common_label_names,
        )
        backup_files_total = GaugeMetricFamily(
            "restic_backup_files_total",
            "Number of files in the backup",
            labels=common_label_names,
        )
        backup_size_total = GaugeMetricFamily(
            "restic_backup_size_total",
            "Total size of backup in bytes",
            labels=common_label_names,
        )
        backup_files_new = GaugeMetricFamily(
            "restic_backup_files_new",
            "Number of new files in the backup",
            labels=common_label_names,
        )
        backup_files_changed = GaugeMetricFamily(
            "restic_backup_files_changed",
            "Number of changed files in the backup",
            labels=common_label_names,
        )
        backup_files_unmodified = GaugeMetricFamily(
            "restic_backup_files_unmodified",
            "Number of unmodified files in the backup",
            labels=common_label_names,
        )
        backup_dirs_new = GaugeMetricFamily(
            "restic_backup_dirs_new",
            "Number of new directories in the backup",
            labels=common_label_names,
        )
        backup_dirs_changed = GaugeMetricFamily(
            "restic_backup_dirs_changed",
            "Number of changed directories in the backup",
            labels=common_label_names,
        )
        backup_dirs_unmodified = GaugeMetricFamily(
            "restic_backup_dirs_unmodified",
            "Number of unmodified directories in the backup",
            labels=common_label_names,
        )
        backup_data_added_bytes = GaugeMetricFamily(
            "restic_backup_data_added_bytes",
            "Number of bytes added in the backup",
            labels=common_label_names,
        )
        backup_duration_seconds = GaugeMetricFamily(
            "restic_backup_duration_seconds",
            "Amount of time Restic took to make the backup",
            labels=common_label_names,
        )

        check_success.add_metric([], self.metrics.check_success)
        locks_total.add_metric([], self.metrics.locks_total)
        scrape_duration_seconds.add_metric([], self.metrics.duration)
        size_total.add_metric([], self.metrics.global_stats.total_size)
        uncompressed_size_total.add_metric([], self.metrics.global_stats.total_uncompressed_size)
        compression_ratio.add_metric([], self.metrics.global_stats.compression_ratio)
        blob_count_total.add_metric([], self.metrics.global_stats.total_blob_count)
        snapshots_total.add_metric([], self.metrics.global_stats.total_snapshots_count)

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
            backup_snapshots_total.add_metric(common_label_values, client.snapshots_total)
            backup_files_total.add_metric(common_label_values, client.stats.total_file_count)
            backup_size_total.add_metric(common_label_values, client.stats.total_size)
            backup_files_new.add_metric(common_label_values, client.stats.files_new)
            backup_files_changed.add_metric(common_label_values, client.stats.files_changed)
            backup_files_unmodified.add_metric(common_label_values, client.stats.files_unmodified)
            backup_dirs_new.add_metric(common_label_values, client.stats.dirs_new)
            backup_dirs_changed.add_metric(common_label_values, client.stats.dirs_changed)
            backup_dirs_unmodified.add_metric(common_label_values, client.stats.dirs_unmodified)
            backup_data_added_bytes.add_metric(common_label_values, client.stats.data_added)
            backup_duration_seconds.add_metric(common_label_values, client.stats.duration)

        yield check_success
        yield locks_total
        yield scrape_duration_seconds
        yield size_total
        yield uncompressed_size_total
        yield compression_ratio
        yield blob_count_total
        yield snapshots_total
        yield backup_timestamp
        yield backup_snapshots_total
        yield backup_files_total
        yield backup_size_total
        yield backup_files_new
        yield backup_files_changed
        yield backup_files_unmodified
        yield backup_dirs_new
        yield backup_dirs_changed
        yield backup_dirs_unmodified
        yield backup_data_added_bytes
        yield backup_duration_seconds

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
        snap_total_counter = self.get_snapshots_counters()

        # get the latest snapshot per hash
        latest_snapshots_dup = self.get_latest_snapshots()
        latest_snapshots: dict[str, ResticSnapshot] = {}
        for snap in latest_snapshots_dup:
            if snap.hash not in latest_snapshots or snap.timestamp > latest_snapshots[snap.hash].timestamp:
                latest_snapshots[snap.hash] = snap

        clients: list[ResticClient] = []
        for snap in list(latest_snapshots.values()):
            if snap.stats is not None:
                stats = snap.stats
            else:
                # this is the legacy way for Restic < 0.17
                stats = self.get_stats_legacy(snap.id)
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
                    snapshots_total=snap_total_counter[snap.hash],
                    stats=stats,
                )
            )

        global_stats = self.get_stats_global()

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
            duration=time.time() - duration,
            global_stats=global_stats,
        )

    def get_snapshots_counters(self) -> dict[str, int]:
        snapshots_data = self.get_snapshots_data(only_latest=False)
        counter: dict[str, int] = {}
        for snap_data in snapshots_data:
            snapshot_hash = self.calc_snapshot_hash(snap_data)
            if snapshot_hash not in counter:
                counter[snapshot_hash] = 1
            else:
                counter[snapshot_hash] += 1
        return counter

    def get_latest_snapshots(self) -> list[ResticSnapshot]:
        snapshots_data = self.get_snapshots_data(only_latest=True)
        snapshots: list[ResticSnapshot] = []
        for snap_data in snapshots_data:
            snapshot_hash = self.calc_snapshot_hash(snap_data)
            snap_timestamp = self.calc_snapshot_timestamp(snap_data)
            snap_stats = self.calc_snapshot_stats(snap_data)
            snapshot = ResticSnapshot(
                time=snap_data["time"],
                hostname=snap_data["hostname"],
                username=snap_data.get("username", ""),
                paths=snap_data.get("paths", []),
                id=snap_data["id"],
                short_id=snap_data["short_id"],
                tags=snap_data.get("tags", []),
                program_version=snap_data.get("program_version", ""),
                hash=snapshot_hash,
                timestamp=snap_timestamp,
                stats=snap_stats,
            )
            snapshots.append(snapshot)
        return snapshots

    def get_snapshots_data(self, only_latest: bool) -> list[dict]:
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
        return json.loads(result.stdout.decode("utf-8"))

    def get_stats_global(self) -> ResticGlobalStats:
        stats = ResticGlobalStats(
            total_size=-1,
            total_uncompressed_size=-1,
            compression_ratio=-1,
            total_blob_count=-1,
            total_snapshots_count=-1,
        )
        if self.disable_global_stats:
            return stats

        stats_data = self.get_stats_data(snapshot_id=None, raw_mode=True)

        stats.total_size = stats_data["total_size"]
        stats.total_uncompressed_size = stats_data["total_uncompressed_size"]
        stats.compression_ratio = stats_data["compression_ratio"]
        stats.total_blob_count = stats_data["total_blob_count"]
        stats.total_snapshots_count = stats_data["snapshots_count"]

        return stats

    def get_stats_legacy(self, snapshot_id: str) -> ResticStats:
        stats = ResticStats(
            total_size=-1,
            total_file_count=-1,
            files_new=-1,
            files_changed=-1,
            files_unmodified=-1,
            dirs_new=-1,
            dirs_changed=-1,
            dirs_unmodified=-1,
            data_added=-1,
            duration=-1,
        )
        if self.disable_legacy_stats:
            return stats

        # We use a local cache because this command is expensive
        if snapshot_id in self.stats_snapshot_cache:
            return self.stats_snapshot_cache[snapshot_id]

        stats_data = self.get_stats_data(snapshot_id=snapshot_id, raw_mode=False)

        stats.total_size = stats_data["total_size"]
        stats.total_file_count = stats_data["total_file_count"]
        self.stats_snapshot_cache[snapshot_id] = stats

        return stats

    def get_stats_data(self, snapshot_id: str | None, raw_mode: bool) -> dict:
        # This command is expensive in CPU/Memory (1-5 seconds)
        cmd = ["restic", "--no-lock", "stats", "--json"]

        if raw_mode:
            cmd.extend(["--mode", "raw-data"])

        if self.insecure_tls:
            cmd.extend(["--insecure-tls"])

        if snapshot_id is not None:
            cmd.append(snapshot_id)

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception("Error executing restic stats command: " + self.parse_stderr(result))
        return json.loads(result.stdout.decode("utf-8"))

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
        return time.mktime(datetime.datetime.fromisoformat(snapshot["time"]).timetuple())

    @staticmethod
    def calc_snapshot_stats(snapshot: dict) -> ResticStats | None:
        if "summary" not in snapshot:
            return None
        summary = snapshot["summary"]
        if "backup_start" in summary and "backup_end" in summary:
            start_time = datetime.datetime.fromisoformat(summary["backup_start"])
            end_time = datetime.datetime.fromisoformat(summary["backup_end"])
            duration = (end_time - start_time).total_seconds()
        else:
            duration = -1
        return ResticStats(
            total_size=summary.get("total_bytes_processed", -1),
            total_file_count=summary.get("total_files_processed", -1),
            files_new=summary.get("files_new", -1),
            files_changed=summary.get("files_changed", -1),
            files_unmodified=summary.get("files_unmodified", -1),
            dirs_new=summary.get("dirs_new", -1),
            dirs_changed=summary.get("dirs_changed", -1),
            dirs_unmodified=summary.get("dirs_unmodified", -1),
            data_added=summary.get("data_added", -1),
            duration=duration,
        )

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


def parse_bool_env(env_var_name: str, default: bool = False) -> bool:
    value = os.environ.get(env_var_name)

    if value is None:
        return default

    # Explicit false values should return False
    if value.strip().lower() in ("false", "0", ""):
        return False

    # Any other set string returns True
    return True


def main(refresh_loop: bool = True) -> None:
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

    if os.environ.get("NO_STATS") is not None:
        logging.error("The environment variable NO_STATS was removed in version 2.0.0. Checkout the changelog.")
        sys.exit(1)

    exporter_address = os.environ.get("LISTEN_ADDRESS", "0.0.0.0")
    exporter_port = int(os.environ.get("LISTEN_PORT", 8001))
    exporter_refresh_interval = int(os.environ.get("REFRESH_INTERVAL", 3600))
    exporter_exit_on_error = parse_bool_env("EXIT_ON_ERROR", False)
    exporter_disable_check = parse_bool_env("NO_CHECK", False)
    exporter_disable_global_stats = parse_bool_env("NO_GLOBAL_STATS", False)
    exporter_disable_legacy_stats = parse_bool_env("NO_LEGACY_STATS", False)
    exporter_disable_locks = parse_bool_env("NO_LOCKS", False)
    exporter_include_paths = parse_bool_env("INCLUDE_PATHS", False)
    exporter_insecure_tls = parse_bool_env("INSECURE_TLS", False)

    try:
        collector = ResticCollector(
            disable_check=exporter_disable_check,
            disable_global_stats=exporter_disable_global_stats,
            disable_legacy_stats=exporter_disable_legacy_stats,
            disable_locks=exporter_disable_locks,
            include_paths=exporter_include_paths,
            insecure_tls=exporter_insecure_tls,
        )
        collector.refresh(exit_on_error=exporter_exit_on_error)
        REGISTRY.register(collector)
        start_http_server(exporter_port, exporter_address)
        logging.info("Serving at http://%s:%d", exporter_address, exporter_port)

        while refresh_loop:
            logging.info("Refreshing stats every %d seconds", exporter_refresh_interval)
            time.sleep(exporter_refresh_interval)
            collector.refresh()

    except KeyboardInterrupt:
        logging.info("\nInterrupted")
        exit(0)


if __name__ == "__main__":
    main()
