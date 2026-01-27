#!/usr/bin/env python
import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from exporter.exporter import ResticCollector, ResticGlobalStats, ResticSnapshot, ResticStats, get_version, main


@pytest.fixture
def restic_collector():
    """Fixture for ResticCollector instance with default params"""
    return ResticCollector(
        disable_check=False,
        disable_global_stats=False,
        disable_legacy_stats=False,
        disable_locks=False,
        include_paths=False,
        insecure_tls=False,
    )


@pytest.fixture
def mock_snapshots_data():
    """Sample snapshots data as returned by restic snapshots --json"""
    summary = {
        "backup_start": "2025-11-20T06:03:53.077541972+01:00",
        "backup_end": "2025-11-20T06:04:26.243226525+01:00",
        "files_new": 2280,
        "files_changed": 3167,
        "files_unmodified": 239163,
        "dirs_new": 1,
        "dirs_changed": 255,
        "dirs_unmodified": 53499,
        "data_blobs": 5576,
        "tree_blobs": 253,
        "data_added": 529759957,
        "data_added_packed": 493326131,
        "total_files_processed": 244610,
        "total_bytes_processed": 67558618674,
    }
    return [
        {
            "time": "2023-01-12T06:59:33.1576588+01:00",
            "hostname": "server1",
            "username": "root",
            "paths": ["/home", "/etc"],
            "id": "abc123b",
            "short_id": "abc123",
            "tags": ["daily", "automated"],
            "program_version": "restic 0.15.0",
            "summary": summary,
        },
        {
            "time": "2023-01-11T06:59:33.1576588+01:00",
            "hostname": "server1",
            "username": "root",
            "paths": ["/home", "/etc"],
            "id": "def456b",
            "short_id": "def456",
            "tags": ["daily"],
            "program_version": "restic 0.15.0",
            "summary": summary,
        },
        {
            "time": "2023-02-11T06:59:33.1576588+01:00",
            "hostname": "server2",
            "username": "backup",
            "paths": ["/var"],
            "id": "ghi789b",
            "short_id": "ghi789",
            "program_version": "restic 0.14.0",
            "summary": summary,
        },
    ]


@pytest.fixture
def mock_stats_data():
    """Sample stats data as returned by restic stats --json"""
    return {
        "total_size": 1073741824,
        "total_file_count": 1000,
    }


@pytest.fixture
def mock_stats_raw_data():
    """Sample stats data as returned by restic stats --json --mode raw-data"""
    return {
        "total_size": 385734388076,
        "total_uncompressed_size": 440775833765,
        "compression_ratio": 1.1426926076348562,
        "compression_progress": 100,
        "compression_space_saving": 12.487400958180794,
        "total_blob_count": 1522470,
        "snapshots_count": 1893,
    }


@pytest.fixture
def mock_subprocess_run():
    """Mock subprocess.run for restic commands"""
    with patch("exporter.exporter.subprocess.run") as mock_run:
        yield mock_run


@pytest.fixture
def mock_restic_cli(mock_subprocess_run, mock_snapshots_data, mock_stats_data, mock_stats_raw_data):
    # noinspection PyUnusedLocal
    def mock_run_side_effect(cmd, **kwargs):
        if "snapshots" in cmd:
            return MagicMock(returncode=0, stdout=json.dumps(mock_snapshots_data).encode("utf-8"), stderr=b"")
        elif "stats" in cmd and "raw-data" not in cmd:
            return MagicMock(returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b"")
        elif "stats" in cmd and "raw-data" in cmd:
            return MagicMock(returncode=0, stdout=json.dumps(mock_stats_raw_data).encode("utf-8"), stderr=b"")
        elif "locks" in cmd:
            return MagicMock(returncode=0, stdout=b"abc123\ndef456\n", stderr=b"")
        elif "check" in cmd:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        else:
            raise ValueError("Unexpected command")

    mock_subprocess_run.side_effect = mock_run_side_effect
    return mock_subprocess_run


class TestResticCollector:
    def test_refresh_success(self, restic_collector, mock_restic_cli):
        restic_collector.refresh()
        # Metrics should be refreshed
        assert restic_collector.metrics is not None
        assert restic_collector.metrics.check_success is not None

        # Error (not exiting)
        restic_collector.metrics = None
        mock_restic_cli.side_effect = Exception("Restic command failed")
        restic_collector.refresh(exit_on_error=False)
        # Metrics should remain unchanged
        assert restic_collector.metrics is None

        # Error (exiting)
        restic_collector.metrics = None
        mock_restic_cli.side_effect = Exception("Restic command failed")
        with pytest.raises(SystemExit):
            restic_collector.refresh(exit_on_error=True)

    def test_collect_metrics(self, restic_collector, mock_restic_cli):
        """Test the collect method that yields Prometheus metrics"""
        restic_collector.refresh()
        metrics = list(restic_collector.collect())

        assert len(metrics) == 20  # All metric families
        metric_names = [m.name for m in metrics]

        assert "restic_check_success" in metric_names
        assert "restic_locks_total" in metric_names
        assert "restic_scrape_duration_seconds" in metric_names
        assert "restic_size_total" in metric_names
        assert "restic_uncompressed_size_total" in metric_names
        assert "restic_compression_ratio" in metric_names
        assert "restic_blob_count_total" in metric_names
        assert "restic_snapshots_total" in metric_names
        assert "restic_backup_timestamp" in metric_names
        assert "restic_backup_snapshots_total" in metric_names
        assert "restic_backup_files_total" in metric_names
        assert "restic_backup_size_total" in metric_names
        assert "restic_backup_files_new" in metric_names
        assert "restic_backup_files_changed" in metric_names
        assert "restic_backup_files_unmodified" in metric_names
        assert "restic_backup_dirs_new" in metric_names
        assert "restic_backup_dirs_changed" in metric_names
        assert "restic_backup_dirs_unmodified" in metric_names
        assert "restic_backup_data_added_bytes" in metric_names
        assert "restic_backup_duration_seconds" in metric_names

    def test_get_metrics_disabled_features(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_global_stats = True
        restic_collector.disable_legacy_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.check_success == 2  # No-check value
        assert metrics.locks_total == 0  # No-locks value
        assert metrics.global_stats.total_size == -1  # No-global-stats value
        assert len(metrics.clients) == 2  # Two unique hashes
        assert metrics.duration >= 0
        # Stats from snapshot summary, paths are disabled
        for client in metrics.clients:
            assert client.snapshot_paths == ""
            assert client.stats.total_size == 67558618674
        # 2 snapshots called
        assert mock_restic_cli.call_count == 2

    def test_get_metrics_with_check(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = False
        restic_collector.disable_global_stats = True
        restic_collector.disable_legacy_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.check_success == 1  # Check passed
        # 2 snapshots + 1 check called
        assert mock_restic_cli.call_count == 3

    def test_get_metrics_with_global_stats(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_global_stats = False
        restic_collector.disable_legacy_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.global_stats.total_size == 385734388076
        # 2 snapshots + 1 global stats called
        assert mock_restic_cli.call_count == 3

    def test_get_metrics_with_legacy_stats(self, restic_collector, mock_subprocess_run, mock_stats_data):
        """Test stats collection when snapshot summary is not available (Restic < 0.17)"""
        snapshots_data = [
            {
                "time": "2024-01-12T06:59:33.1576588+01:00",
                "hostname": "server2",
                "paths": ["/home", "/var"],
                "id": "abc123b",
                "short_id": "abc123",
            },
            {
                "time": "2023-02-11T06:59:33.1576588+01:00",
                "hostname": "server2",
                "username": "backup",
                "paths": ["/var"],
                "id": "ghi789b",
                "short_id": "ghi789",
            },
        ]

        # noinspection PyUnusedLocal
        def mock_run_side_effect(cmd, **kwargs):
            if "snapshots" in cmd:
                return MagicMock(returncode=0, stdout=json.dumps(snapshots_data).encode("utf-8"), stderr=b"")
            elif "stats" in cmd:
                return MagicMock(returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b"")
            else:
                raise ValueError("Unexpected command")

        mock_subprocess_run.side_effect = mock_run_side_effect

        restic_collector.disable_check = True
        restic_collector.disable_global_stats = True
        restic_collector.disable_legacy_stats = False
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        # Verify stats are collected
        for client in metrics.clients:
            assert client.stats.total_size == 1073741824
            assert client.stats.total_file_count == 1000
            assert client.stats.files_new == -1
        # 2 snapshots + 2 stats called
        assert mock_subprocess_run.call_count == 4

        # Stats disabled
        restic_collector.disable_legacy_stats = True
        metrics = restic_collector.get_metrics()

        # Verify stats are collected
        for client in metrics.clients:
            assert client.stats.total_size == -1
            assert client.stats.total_file_count == -1
            assert client.stats.files_new == -1
        # previous calls + 2 snapshots (no new stats calls)
        assert mock_subprocess_run.call_count == 6

    def test_get_metrics_with_locks(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_global_stats = True
        restic_collector.disable_legacy_stats = True
        restic_collector.disable_locks = False
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.locks_total == 2
        # 2 snapshots + 1 lock called
        assert mock_restic_cli.call_count == 3

    def test_get_metrics_with_paths(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_global_stats = True
        restic_collector.disable_legacy_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = True
        metrics = restic_collector.get_metrics()

        # Verify paths are included
        for client in metrics.clients:
            assert client.snapshot_paths != ""
        # 2 snapshots
        assert mock_restic_cli.call_count == 2

    def test_get_metrics_snapshot_counter(self, restic_collector, mock_restic_cli):
        """Test that snapshot counter works correctly"""
        restic_collector.disable_check = True
        restic_collector.disable_global_stats = True
        restic_collector.disable_legacy_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert len(metrics.clients) == 2  # There are 3 snapshots, but only 2 unique hashes
        client_1 = metrics.clients[0]
        assert client_1.snapshots_total == 2
        assert client_1.timestamp == 1673503173.0  # Timestamp of newest snapshot

        client_2 = metrics.clients[1]
        assert client_2.snapshots_total == 1

    def test_get_snapshots_counters(self, restic_collector, mock_subprocess_run, mock_snapshots_data):
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_snapshots_data).encode("utf-8"), stderr=b""
        )
        snapshots_counters = restic_collector.get_snapshots_counters()
        assert snapshots_counters == {
            "71f88da2c5cab9b10885214531b4f3dc1a5e0016ec67699595da597f0e652a4c": 1,
            "80873a9c92e8448f9fe8d78e6f6fbe856818af6ab2a86e522d0e4c5612b27eb8": 2,
        }

    def test_get_latest_snapshots(self, restic_collector, mock_subprocess_run, mock_snapshots_data):
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_snapshots_data).encode("utf-8"), stderr=b""
        )
        snapshots = restic_collector.get_latest_snapshots()
        assert len(snapshots) == 3
        assert snapshots[0] == ResticSnapshot(
            time="2023-01-12T06:59:33.1576588+01:00",
            hostname="server1",
            username="root",
            paths=["/home", "/etc"],
            id="abc123b",
            short_id="abc123",
            tags=["daily", "automated"],
            program_version="restic 0.15.0",
            hash="80873a9c92e8448f9fe8d78e6f6fbe856818af6ab2a86e522d0e4c5612b27eb8",
            timestamp=1673503173.0,
            stats=ResticStats(
                total_size=67558618674,
                total_file_count=244610,
                files_new=2280,
                files_changed=3167,
                files_unmodified=239163,
                dirs_new=1,
                dirs_changed=255,
                dirs_unmodified=53499,
                data_added=529759957,
                duration=33.165685,
            ),
        )

    def test_get_latest_snapshots_missing_values(self, restic_collector, mock_subprocess_run):
        snapshots_data = [
            {
                "time": "2024-01-12T06:59:33.1576588+01:00",
                "hostname": "server2",
                "paths": ["/home", "/var"],
                "id": "abc123b",
                "short_id": "abc123",
            }
        ]
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(snapshots_data).encode("utf-8"), stderr=b""
        )
        snapshots = restic_collector.get_latest_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0] == ResticSnapshot(
            time="2024-01-12T06:59:33.1576588+01:00",
            hostname="server2",
            username="",
            paths=["/home", "/var"],
            id="abc123b",
            short_id="abc123",
            tags=[],
            program_version="",
            hash="ba37d8a42f3028c561e65b08b9cbf8088d1375cd5fbece0850252be16e7f0043",
            timestamp=1705039173.0,
            stats=None,
        )

    def test_get_snapshots_data(self, restic_collector, mock_subprocess_run, mock_snapshots_data):
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_snapshots_data).encode("utf-8"), stderr=b""
        )
        snapshots_data = restic_collector.get_snapshots_data(only_latest=False)
        assert snapshots_data == mock_snapshots_data
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "snapshots",
            "--json",
        ]

        # Flag only_latest=True
        restic_collector.get_snapshots_data(only_latest=True)
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "snapshots",
            "--json",
            "--latest",
            "1",
        ]

        # Error
        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"Error: repository not found")
        with pytest.raises(Exception, match="Error executing restic snapshot command"):
            restic_collector.get_snapshots_data(only_latest=False)

        # Insecure TLS
        restic_collector.insecure_tls = True
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_snapshots_data).encode("utf-8"), stderr=b""
        )
        restic_collector.get_snapshots_data(only_latest=False)
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "snapshots",
            "--json",
            "--insecure-tls",
        ]

    def test_get_stats_global(self, restic_collector, mock_subprocess_run, mock_stats_raw_data):
        assert len(restic_collector.stats_snapshot_cache) == 0
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_stats_raw_data).encode("utf-8"), stderr=b""
        )
        stats = restic_collector.get_stats_global()
        assert stats == ResticGlobalStats(
            total_size=385734388076,
            total_uncompressed_size=440775833765,
            compression_ratio=1.1426926076348562,
            total_blob_count=1522470,
            total_snapshots_count=1893,
        )
        assert mock_subprocess_run.call_count == 1

        # Disabled stats
        restic_collector.disable_global_stats = True
        stats = restic_collector.get_stats_global()
        assert stats == ResticGlobalStats(
            total_size=-1,
            total_uncompressed_size=-1,
            compression_ratio=-1,
            total_blob_count=-1,
            total_snapshots_count=-1,
        )
        assert mock_subprocess_run.call_count == 1  # No new call

    def test_get_stats_legacy(self, restic_collector, mock_subprocess_run, mock_stats_data):
        assert len(restic_collector.stats_snapshot_cache) == 0
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b""
        )
        stats_1 = restic_collector.get_stats_legacy("abc123")
        assert stats_1 == ResticStats(
            total_size=1073741824,
            total_file_count=1000,
            files_new=-1,
            files_changed=-1,
            files_unmodified=-1,
            dirs_new=-1,
            dirs_changed=-1,
            dirs_unmodified=-1,
            data_added=-1,
            duration=-1,
        )
        assert mock_subprocess_run.call_count == 1
        assert len(restic_collector.stats_snapshot_cache) == 1
        assert restic_collector.stats_snapshot_cache["abc123"] == stats_1

        # Cached value (2nd call, value is cached, so no new subprocess call)
        stats_2 = restic_collector.get_stats_legacy("abc123")
        assert stats_2 == stats_1
        assert mock_subprocess_run.call_count == 1  # No new call

        # Disabled stats
        restic_collector.disable_legacy_stats = True
        stats = restic_collector.get_stats_legacy("xyz444")
        assert stats == ResticStats(
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
        assert mock_subprocess_run.call_count == 1  # No new call

    def test_get_stats_data(self, restic_collector, mock_subprocess_run, mock_stats_data, mock_stats_raw_data):
        # snapshot_id, raw_mode=False (used by get_stats_snapshot)
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b""
        )
        stats = restic_collector.get_stats_data(snapshot_id="abc123", raw_mode=False)
        assert stats == mock_stats_data
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "stats",
            "--json",
            "abc123",
        ]
        assert mock_subprocess_run.call_count == 1

        # snapshot_id=None, raw_mode=True (used by get_stats_global)
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_stats_raw_data).encode("utf-8"), stderr=b""
        )
        stats = restic_collector.get_stats_data(snapshot_id=None, raw_mode=True)
        assert stats == mock_stats_raw_data
        assert mock_subprocess_run.call_args[0][0] == ["restic", "--no-lock", "stats", "--json", "--mode", "raw-data"]
        assert mock_subprocess_run.call_count == 2

        # Error
        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"Error: snapshot not found")
        with pytest.raises(Exception, match="Error executing restic stats command"):
            restic_collector.get_stats_data(snapshot_id="xyz222", raw_mode=False)
        assert mock_subprocess_run.call_count == 3

        # Insecure TLS
        restic_collector.insecure_tls = True
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b""
        )
        stats = restic_collector.get_stats_data(snapshot_id="xyz333", raw_mode=False)
        assert stats == mock_stats_data
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "stats",
            "--json",
            "--insecure-tls",
            "xyz333",
        ]
        assert mock_subprocess_run.call_count == 4

    def test_get_check(self, restic_collector, mock_subprocess_run, caplog):
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        result = restic_collector.get_check()
        assert result == 1  # Success
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "check",
        ]

        # Error
        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"Error: repository corrupted")
        result = restic_collector.get_check()
        assert result == 0  # Failure
        assert caplog.messages == ["Error checking the repository health. Error: repository corrupted Exit code: 1"]

        # Insecure TLS
        restic_collector.insecure_tls = True
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        restic_collector.get_check()
        result = restic_collector.get_check()
        assert result == 1  # Success
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "check",
            "--insecure-tls",
        ]

    def test_get_locks(self, restic_collector, mock_subprocess_run):
        locks_output = "abc123def456\nghi789jkl012\nbad line\nmno345pqr678\n"
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=locks_output.encode("utf-8"), stderr=b"")
        result = restic_collector.get_locks()
        assert result == 3  # Three lock IDs
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "list",
            "locks",
        ]

        # Empty locks
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=b"\n", stderr=b"")
        result = restic_collector.get_locks()
        assert result == 0

        # Error
        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"Error: cannot list locks")
        with pytest.raises(Exception, match="Error executing restic list locks command"):
            restic_collector.get_locks()

        # Insecure TLS
        restic_collector.insecure_tls = True
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=b"abc123\n", stderr=b"")
        result = restic_collector.get_locks()
        assert result == 1
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "list",
            "locks",
            "--insecure-tls",
        ]

    def test_calc_snapshot_hash(self):
        snapshot = {
            "hostname": "server1",
            "username": "root",
            "paths": ["/home", "/etc"],
        }
        assert (
            ResticCollector.calc_snapshot_hash(snapshot)
            == "80873a9c92e8448f9fe8d78e6f6fbe856818af6ab2a86e522d0e4c5612b27eb8"
        )

        del snapshot["username"]
        assert (
            ResticCollector.calc_snapshot_hash(snapshot)
            == "068a07fc863fce525fc7ff6ccb22f102c98bcb8137d89430a1813b054a6626a0"
        )

    def test_calc_snapshot_timestamp(self):
        # Restic >= 0.14: '2023-01-12T06:59:33.1576588+01:00'
        snapshot = {"time": "2023-01-12T06:59:33.1576588+01:00"}
        assert ResticCollector.calc_snapshot_timestamp(snapshot) == 1673503173.0

        # Restic 0.12: '2023-02-01T14:14:19.30760523Z'
        snapshot["time"] = "2023-02-01T14:14:19.30760523Z"
        assert ResticCollector.calc_snapshot_timestamp(snapshot) == 1675257259.0

    def test_calc_snapshot_stats(self):
        snapshot = {
            "summary": {
                "backup_start": "2025-12-08T07:12:00.913147689+01:00",
                "backup_end": "2025-12-08T07:12:04.006656036+01:00",
                "files_new": 0,
                "files_changed": 14,
                "files_unmodified": 25889,
                "dirs_new": 0,
                "dirs_changed": 17,
                "dirs_unmodified": 5475,
                "data_blobs": 2,
                "tree_blobs": 18,
                "data_added": 473450,
                "data_added_packed": 35460,
                "total_files_processed": 25903,
                "total_bytes_processed": 12382567073,
            }
        }
        stats = ResticCollector.calc_snapshot_stats(snapshot)
        assert stats == ResticStats(
            total_size=12382567073,
            total_file_count=25903,
            files_new=0,
            files_changed=14,
            files_unmodified=25889,
            dirs_new=0,
            dirs_changed=17,
            dirs_unmodified=5475,
            data_added=473450,
            duration=3.093509,
        )

        # Missing fields
        stats = ResticCollector.calc_snapshot_stats({"summary": {}})
        assert stats == ResticStats(
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

        # Missing summary (Restic < 0.17)
        assert ResticCollector.calc_snapshot_stats({}) is None

    def test_parse_stderr(self):
        mock_result = MagicMock()
        mock_result.stderr = b"Error: repository not found\n"
        mock_result.returncode = 1

        result = ResticCollector.parse_stderr(mock_result)
        assert result == "Error: repository not found  Exit code: 1"


class TestParseBoolEnv:
    """Test the parse_bool_env() helper function for boolean environment variable parsing"""

    def test_false_values_false_string(self):
        """Test that 'false' string correctly parses as False"""
        with patch.dict(os.environ, {"TEST_VAR": "false"}):
            assert parse_bool_env("TEST_VAR") is False

    def test_false_values_false_uppercase(self):
        """Test that 'False' string correctly parses as False"""
        with patch.dict(os.environ, {"TEST_VAR": "False"}):
            assert parse_bool_env("TEST_VAR") is False

    def test_false_values_zero_string(self):
        """Test that '0' string correctly parses as False"""
        with patch.dict(os.environ, {"TEST_VAR": "0"}):
            assert parse_bool_env("TEST_VAR") is False

    def test_false_values_empty_string(self):
        """Test that empty string correctly parses as False"""
        with patch.dict(os.environ, {"TEST_VAR": ""}):
            assert parse_bool_env("TEST_VAR") is False

    def test_true_values_true_string(self):
        """Test that 'true' string correctly parses as True"""
        with patch.dict(os.environ, {"TEST_VAR": "true"}):
            assert parse_bool_env("TEST_VAR") is True

    def test_true_values_true_uppercase(self):
        """Test that 'True' string correctly parses as True"""
        with patch.dict(os.environ, {"TEST_VAR": "True"}):
            assert parse_bool_env("TEST_VAR") is True

    def test_true_values_one_string(self):
        """Test that '1' string correctly parses as True"""
        with patch.dict(os.environ, {"TEST_VAR": "1"}):
            assert parse_bool_env("TEST_VAR") is True

    def test_true_values_arbitrary_string(self):
        """Test that arbitrary non-empty strings parse as True (lenient behavior)"""
        with patch.dict(os.environ, {"TEST_VAR": "anything"}):
            assert parse_bool_env("TEST_VAR") is True

    def test_default_false_when_unset(self):
        """Test that unset variable returns default False"""
        with patch.dict(os.environ, {}, clear=True):
            assert parse_bool_env("NONEXISTENT_VAR", False) is False

    def test_default_true_when_unset(self):
        """Test that unset variable returns default True"""
        with patch.dict(os.environ, {}, clear=True):
            assert parse_bool_env("NONEXISTENT_VAR", True) is True


class TestMain:
    @patch("exporter.exporter.start_http_server")
    @patch("exporter.exporter.REGISTRY.register")
    @patch.dict(
        os.environ,
        {
            "RESTIC_REPOSITORY": "/path/to/repo",
            "RESTIC_PASSWORD": "password",
        },
    )
    def test_main(self, mock_register, mock_start_server, mock_restic_cli, caplog):
        caplog.set_level(logging.INFO)
        main(refresh_loop=False)

        # Collector registered with default params
        mock_register.assert_called_once()
        collector = mock_register.call_args[0][0]
        assert collector.disable_check is False
        assert collector.disable_global_stats is False
        assert collector.disable_legacy_stats is False
        assert collector.disable_locks is False
        assert collector.include_paths is False
        assert collector.insecure_tls is False
        # The collector has metrics after first refresh
        assert collector.metrics is not None

        # Server starts
        mock_start_server.assert_called_once_with(8001, "0.0.0.0")

        # Check logs
        version = get_version()
        assert caplog.messages == [
            f"Starting Restic Prometheus Exporter v{version}",
            "It could take a while if the repository is remote",
            "Serving at http://0.0.0.0:8001",
        ]

    @patch("exporter.exporter.start_http_server")
    @patch("exporter.exporter.REGISTRY.register")
    @patch.dict(
        os.environ,
        {
            "RESTIC_REPOSITORY": "/path/to/repo",
            "RESTIC_PASSWORD": "password",
            "LISTEN_ADDRESS": "127.0.0.1",
            "LISTEN_PORT": "8002",
            "NO_CHECK": "True",
            "NO_GLOBAL_STATS": "True",
            "NO_LEGACY_STATS": "True",
            "NO_LOCKS": "True",
            "INCLUDE_PATHS": "True",
            "INSECURE_TLS": "True",
        },
    )
    def test_main_env_vars(self, mock_register, mock_start_server, mock_restic_cli):
        main(refresh_loop=False)

        # Collector registered with default params
        mock_register.assert_called_once()
        collector = mock_register.call_args[0][0]
        assert collector.disable_check is True
        assert collector.disable_global_stats is True
        assert collector.disable_legacy_stats is True
        assert collector.disable_locks is True
        assert collector.include_paths is True
        assert collector.insecure_tls is True
        # The collector has metrics after first refresh
        assert collector.metrics is not None

        # Server starts
        mock_start_server.assert_called_once_with(8002, "127.0.0.1")

    @patch("exporter.exporter.start_http_server")
    @patch("exporter.exporter.REGISTRY.register")
    @patch("sys.exit")
    @patch.dict(
        os.environ,
        {
            "NO_STATS": "True",
        },
    )
    def test_main_error(self, mock_sys_exit, _mock_register, _mock_start_server, mock_restic_cli, caplog):
        caplog.set_level(logging.ERROR)

        main(refresh_loop=False)
        assert mock_sys_exit.call_count == 3
        assert "The environment variable RESTIC_REPOSITORY is mandatory" in caplog.messages
        assert (
            "One of the environment variables RESTIC_PASSWORD, RESTIC_PASSWORD_FILE or "
            "RESTIC_PASSWORD_COMMAND is mandatory"
        ) in caplog.messages
        assert (
            "The environment variable NO_STATS was removed in version 2.0.0. Checkout the changelog." in caplog.messages
        )
