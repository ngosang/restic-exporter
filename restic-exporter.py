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
import calendar

from dateutil import parser
from datetime import datetime, timedelta

from prometheus_client import start_http_server
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY


class ResticCollector(object):
    def __init__(self, repository, password_file_path, storage_boxes, **kwargs):
        # required stuff - repository, path to password file,
        # list of storageboxes where repository for host is placed
        self.repository = repository
        self.password_file_path = password_file_path
        self.storage_boxes = storage_boxes
        self.repository_name = kwargs.get('repository_name', 'default')
        self.retention_policy = kwargs.get('retention_policy', None)
        self.backup_times = kwargs.get('backup_times', [3])

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

        retention_policy_labels = [
            'policy_name',
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
        retention_policy_labels.extend(common_host_labels)

        # add common host labels to per_tag_label_names and common_label_names
        common_label_names.extend(common_host_labels)
        per_tag_label_names.extend(common_host_labels)

        check_success = GaugeMetricFamily(
            "restic_check_success",
            "Result of restic check operation in the repository",
            labels=common_host_labels,
        )
        locks_total = GaugeMetricFamily(
            "restic_locks_total",
            "Total number of locks in the repository",
            labels=common_host_labels,
        )
        snapshots_total = GaugeMetricFamily(
            "restic_snapshots_total",
            "Total number of snapshots in the repository",
            labels=common_host_labels,
        )
        backup_timestamp = GaugeMetricFamily(
            "restic_backup_timestamp",
            "Timestamp of the last backup",
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
        backup_snapshots_total = GaugeMetricFamily(
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

        snapshots_by_retention_policy = GaugeMetricFamily(
            "restic_snapshots_by_retention_policy",
            "Number of snapshots by retention policy",
            labels=retention_policy_labels,
        )

        # this metrics is present only because we cannot use values from labels as grafana max values
        snapshot_retention_policy = GaugeMetricFamily(
            "restic_snapshot_retention_policy",
            "Retention policy for type of snapshot",
            labels=retention_policy_labels,
        )

        snapshots_by_retention_policy_state = GaugeMetricFamily(
            "restic_snapshots_by_retention_policy_state",
            "State of retention policy for type of snapshot",
            labels=retention_policy_labels,
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

            for policy_name, policy_data in metric["snapshots_by_policy"].items():
                by_policy_label_values = [
                    policy_name,
                ]

                by_policy_label_values.extend(common_host_label_values)

                snapshot_retention_policy.add_metric(by_policy_label_values, policy_data['policy'])
                snapshots_by_retention_policy.add_metric(by_policy_label_values, policy_data['found'])
                snapshots_by_retention_policy_state.add_metric(by_policy_label_values, int(policy_data['expected'] <= policy_data['found']))

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
            yield snapshot_retention_policy
            yield snapshots_by_retention_policy
            yield snapshots_by_retention_policy_state
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

    def _parse_timestamp(self, timestamp):
        parsed_timestamp = None
        # New implementation: using dateutil.parser
        try:
            parsed_timestamp = parser.parse(timestamp).timestamp()

        # fallback using old implementation with regex parsing
        except Exception as e:
            logging.warning(f"datetuil.parser: Unable to parse timestamp: {timestamp}, defaulting to regex parsing")
            time_parsed = re.sub(r"\.[^+-]+", "", snap["time"])
            if len(time_parsed) > 19:
                # restic 14: '2023-01-12T06:59:33.1576588+01:00' ->
                # '2023-01-12T06:59:33+01:00'
                time_format = "%Y-%m-%dT%H:%M:%S%z"
            else:
                # restic 12: '2023-02-01T14:14:19.30760523Z' ->
                # '2023-02-01T14:14:19'
                time_format = "%Y-%m-%dT%H:%M:%S"

            # simplified: absolutely no need to call time.mktime()
            parsed_timestamp = datetime.strptime(time_parsed, time_format).astimezone().timestamp()

        finally:
            return str(round(parsed_timestamp))

    def _parse_metrics(self, storagebox: str = None):
        start_time = time.time()

        today = datetime.now().astimezone()

        all_snapshots = self.get_snapshots(storagebox)

        snap_total_counter = {}
        snap_by_type_total_counter = {}
        snap_by_type_retention_policy = {
            'manual': {'policy': self.retention_policy.get('manual', 0), 'expected': 0, 'found': 0},
            'update': {'policy': self.retention_policy.get('update', 0), 'expected': 0, 'found': 0},
            'hourly': {'policy': self.retention_policy.get('hourly', 0), 'expected': 0, 'found': 0},
            'daily': {'policy': self.retention_policy.get('daily', 0), 'expected': 0, 'found': 0},
            'weekly': {'policy': self.retention_policy.get('weekly', 0), 'expected': 0, 'found': 0},
            'monthly': {'policy': self.retention_policy.get('monthly', 0), 'expected': 0, 'found': 0},
            'yearly': {'policy': self.retention_policy.get('yearly', 0), 'expected': 0, 'found': 0},
        }

        # to calculate snapshots_by_retention_policy_state, we need the oldest snapshot timestamp
        # so we can precisely calculate when the backups have started, so we can compare the counts
        oldest_snapshot = today.timestamp()

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
                "snapshot_timestamp": self._parse_timestamp(snap["time"]),
                "total_size": snap_stats.get('total_size', 0),
                "total_file_count": snap_stats.get('total_file_count', 0),
            }

            if oldest_snapshot > float(snapshot_stats[snap["id"]]["snapshot_timestamp"]):
                oldest_snapshot = float(snapshot_stats[snap["id"]]["snapshot_timestamp"])

        # calculate possible number of backups for each retention policy, based on oldest_snapshot value
        # this is required to determine if the retention policy is fulfilled or not
        # for daily backups, we need to calculate the number of days between oldest_snapshot and today
        # for weekly backups, we need to calculate the number of weeks between oldest_snapshot and today
        # for monthly backups, we need to calculate the number of months between oldest_snapshot and today
        # for yearly backups, we need to calculate the number of years between oldest_snapshot, and today
        # we will not alert for manual and update snapshots, since they aren't automated
        max_daily_snaps = round((today.timestamp() - oldest_snapshot) / timedelta(days=1).total_seconds())
        if today.timestamp() - oldest_snapshot >= 7:
            max_weekly_snaps = round((today.timestamp() - oldest_snapshot) / timedelta(weeks=1).total_seconds())
        else:
            max_weekly_snaps = 0

        if today.timestamp() - oldest_snapshot >= 30:
            max_monthly_snaps = round((today.timestamp() - oldest_snapshot) / timedelta(days=30).total_seconds())
        else:
            max_monthly_snaps = 0

        if today.timestamp() - oldest_snapshot >= 365:
            max_yearly_snaps = round((today.timestamp() - oldest_snapshot) / timedelta(days=365).total_seconds())
        else:
            max_yearly_snaps = 0

        snap_by_type_retention_policy['hourly']['expected'] = 0
        snap_by_type_retention_policy['daily']['expected'] = min(max_daily_snaps, self.retention_policy.get('daily', 0))
        snap_by_type_retention_policy['weekly']['expected'] = min(max_weekly_snaps, self.retention_policy.get('weekly', 0))
        snap_by_type_retention_policy['monthly']['expected'] = min(max_monthly_snaps, self.retention_policy.get('monthly', 0))
        snap_by_type_retention_policy['yearly']['expected'] = min(max_yearly_snaps, self.retention_policy.get('yearly', 0))

        # calculate expected number of hourly backups, based on time passed between start of the day and now
        # if hour is in self.backup_times, we'll count it as expected backup
        for hour in range(0, today.hour+1):
            if hour in self.backup_times:
                snap_by_type_retention_policy['hourly']['expected'] += 1

        for tag, count in snap_by_type_total_counter.items():
            # count manual backups
            if tag in ['manual', 'pre-restore']:
                snap_by_type_retention_policy['manual']['found'] += count

            # count update
            if tag in ['update', 'sync-envs']:
                snap_by_type_retention_policy['update']['found'] += count

            if tag == 'SLA':
                # this is where stuff gets complicated...
                # we have multiple policies for SLA backups (hourly, daily, monthly, yearly, etc)
                # but they are all tagged with SLA
                # restic snapshots doesn't return data about retention, so we need to go through
                # all SLA backups, determine which category they belong to and count them

                # extract all SLA backups from snapshot_stats
                sla_backups = {snap_id: snap_data for snap_id, snap_data in snapshot_stats.items()
                               if snap_data['snapshot_tag'] == 'SLA'}

                # requred for extraction of daily backups
                hourly_start_timestamp = today.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                hourly_stop_timestamp = today.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()

                backups_for_date = {}
                backups_for_week = {}
                backups_for_month = {}
                backups_for_year = {}

                current_date = datetime.now()

                # we need to determine number of weeks covered by the weekly retention policy
                weekly_start = (current_date - timedelta(weeks=self.retention_policy.get('weekly', 1))).timestamp()

                # same thing for monthly retention policy
                monthly_start = (current_date - timedelta(days=30 * self.retention_policy.get('monthly', 1))).timestamp()

                # same thing for yearly retention policy
                yearly_start = (current_date - timedelta(days=365 * self.retention_policy.get('yearly', 1))).timestamp()

                for snap_id, snap_data in sla_backups.items():
                    snapshot_timestamp = float(snap_data['snapshot_timestamp'])
                    # count hourly backups

                    if hourly_start_timestamp <= snapshot_timestamp <= hourly_stop_timestamp:
                        snap_by_type_retention_policy['hourly']['found'] += 1

                    # what are we doing here is basically we count the backups per day/week/month/year
                    # and based on the number of keys in the dict, we can determine how many backups
                    # for that period we have... and then, based on that, we can determine if the retention
                    # policy is fulfilled or not
                    backup_date = datetime.fromtimestamp(snapshot_timestamp).astimezone()

                    # daily limit
                    daily_start = backup_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                    daily_end = backup_date.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()

                    day_key = backup_date.strftime('%Y%m%d')
                    week_key = backup_date.strftime('%Y%W')
                    month_key = backup_date.strftime('%Y%m')
                    year_key = backup_date.strftime('%Y')

                    # number of keys provides us with the info about daily backups
                    # while number of values for the day provides us with the info about
                    # hourly backups. this also provides us with a mechanism to extract
                    # the latest backup for each day
                    if daily_start <= snapshot_timestamp <= daily_end:
                        if day_key not in backups_for_date:
                            backups_for_date[day_key] = 1
                        else:
                            backups_for_date[day_key] += 1

                    if yearly_start <= snapshot_timestamp <= current_date.timestamp():
                        if year_key not in backups_for_year:
                            backups_for_year[year_key] = 1
                        else:
                            backups_for_year[year_key] += 1

                    # helps us count the weekly backups (number of keys)
                    # and number of daily backups (values of the keys)
                    if weekly_start <= snapshot_timestamp <= current_date.timestamp():
                        if week_key not in backups_for_date:
                            backups_for_week[week_key] = 1
                        else:
                            backups_for_week[week_key] += 1

                    if monthly_start <= snapshot_timestamp <= current_date.timestamp():
                        if month_key not in backups_for_date:
                            backups_for_month[month_key] = 1
                        else:
                            backups_for_month[month_key] += 1

                snap_by_type_retention_policy['daily']['found'] = len(backups_for_date.keys())
                snap_by_type_retention_policy['weekly']['found'] = len(backups_for_week.keys())
                snap_by_type_retention_policy['monthly']['found'] = len(backups_for_month.keys())
                snap_by_type_retention_policy['yearly']['found'] = len(backups_for_year.keys())

        latest_snapshots_dup = self.get_snapshots(storagebox, True)
        latest_snapshots = {}
        for snap in latest_snapshots_dup:
            snap["timestamp"] = self._parse_timestamp(snap["time"])
            if snap["hash"] not in latest_snapshots or snap["timestamp"] > latest_snapshots[snap["hash"]]["timestamp"]:
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
                    "storagebox": storagebox if storagebox else 'local',
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
            "snapshots_by_policy": snap_by_type_retention_policy,
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
    retention_policy_string = os.environ.get('RESTIC_RETENTION_POLICY', None)
    backup_times_string = os.environ.get('BACKUP_TIMES', None)

    # retention policy should be sent as a POLICY=VALUE comma separated list
    # so if we have it, we need to split it and create a dict
    retention_policy = {}
    if retention_policy_string:
        for policy in retention_policy_string.split(','):
            policy_name, policy_value = policy.split('=')
            retention_policy[policy_name] = int(policy_value)

    backup_times = [3]
    if backup_times_string:
        backup_times = [int(x) for x in backup_times_string.split(',')]

    # repository info
    repository_name = os.environ.get('RESTIC_REPOSITORY_NAME', 'default')

    try:
        collector = ResticCollector(
            repository,
            password_file,
            storageboxes,
            # rclone and restic params
            rclone_program=rclone_program,
            filter_hosts=filter_hosts,
            retention_policy=retention_policy,
            repository_name=repository_name,
            backup_times=backup_times,
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
