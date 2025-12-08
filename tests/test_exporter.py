#!/usr/bin/env python
import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from exporter.exporter import ResticCollector, get_version, main


@pytest.fixture
def restic_collector():
    """Fixture for ResticCollector instance with default params"""
    return ResticCollector(
        disable_check=False,
        disable_stats=False,
        disable_locks=False,
        include_paths=False,
        insecure_tls=False,
    )


@pytest.fixture
def mock_snapshots_data():
    """Sample snapshots data as returned by restic snapshots --json"""
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
        },
        {
            "time": "2023-02-11T06:59:33.1576588+01:00",
            "hostname": "server2",
            "username": "backup",
            "paths": ["/var"],
            "id": "ghi789b",
            "short_id": "ghi789",
            "program_version": "restic 0.14.0",
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
def mock_subprocess_run():
    """Mock subprocess.run for restic commands"""
    with patch("exporter.exporter.subprocess.run") as mock_run:
        yield mock_run


@pytest.fixture
def mock_restic_cli(mock_subprocess_run, mock_snapshots_data, mock_stats_data):
    # noinspection PyUnusedLocal
    def mock_run_side_effect(cmd, **kwargs):
        if "snapshots" in cmd:
            return MagicMock(returncode=0, stdout=json.dumps(mock_snapshots_data).encode("utf-8"), stderr=b"")
        elif "stats" in cmd:
            return MagicMock(returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b"")
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

        assert len(metrics) == 8  # All metric families
        metric_names = [m.name for m in metrics]

        assert "restic_check_success" in metric_names
        assert "restic_locks" in metric_names
        assert "restic_snapshots" in metric_names
        assert "restic_backup_timestamp" in metric_names
        assert "restic_backup_files" in metric_names
        assert "restic_backup_size" in metric_names
        assert "restic_backup_snapshots" in metric_names
        assert "restic_scrape_duration_seconds" in metric_names

    def test_get_metrics_disabled_features(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.check_success == 2  # No-check value
        assert metrics.locks_total == 0  # No-locks value
        assert metrics.snapshots_total == 3
        assert len(metrics.clients) == 2  # Two unique hashes
        assert metrics.duration >= 0
        # Verify stats and paths are disabled
        for client in metrics.clients:
            assert client.size_total == -1
            assert client.files_total == -1
            assert client.snapshot_paths == ""
        # 2 snapshots called
        assert mock_restic_cli.call_count == 2

    def test_get_metrics_with_check(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = False
        restic_collector.disable_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.check_success == 1  # Check passed
        # 2 snapshots + 1 check called
        assert mock_restic_cli.call_count == 3

    def test_get_metrics_with_stats(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_stats = False
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        # Verify stats are collected
        for client in metrics.clients:
            assert client.size_total == 1073741824
            assert client.files_total == 1000
        # 2 snapshots + 2 stats called
        assert mock_restic_cli.call_count == 4

    def test_get_metrics_with_locks(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_stats = True
        restic_collector.disable_locks = False
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.locks_total == 2
        # 2 snapshots + 1 lock called
        assert mock_restic_cli.call_count == 3

    def test_get_metrics_with_paths(self, restic_collector, mock_restic_cli):
        restic_collector.disable_check = True
        restic_collector.disable_stats = True
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
        restic_collector.disable_stats = True
        restic_collector.disable_locks = True
        restic_collector.include_paths = False
        metrics = restic_collector.get_metrics()

        assert metrics.snapshots_total == 3  # Total snapshots
        assert len(metrics.clients) == 2  # Two unique hashes
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
        first_snapshot = snapshots[0]
        assert first_snapshot.time == "2023-01-12T06:59:33.1576588+01:00"
        assert first_snapshot.hostname == "server1"
        assert first_snapshot.username == "root"
        assert first_snapshot.paths == ["/home", "/etc"]
        assert first_snapshot.id == "abc123b"
        assert first_snapshot.short_id == "abc123"
        assert first_snapshot.tags == ["daily", "automated"]
        assert first_snapshot.program_version == "restic 0.15.0"
        assert first_snapshot.hash == "80873a9c92e8448f9fe8d78e6f6fbe856818af6ab2a86e522d0e4c5612b27eb8"
        assert first_snapshot.timestamp == 1673503173.0

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
        first_snapshot = snapshots[0]
        assert first_snapshot.time == "2024-01-12T06:59:33.1576588+01:00"
        assert first_snapshot.hostname == "server2"
        assert first_snapshot.username == ""
        assert first_snapshot.paths == ["/home", "/var"]
        assert first_snapshot.id == "abc123b"
        assert first_snapshot.short_id == "abc123"
        assert first_snapshot.tags == []
        assert first_snapshot.program_version == ""
        assert first_snapshot.hash == "ba37d8a42f3028c561e65b08b9cbf8088d1375cd5fbece0850252be16e7f0043"
        assert first_snapshot.timestamp == 1705039173.0

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

    def test_get_stats(self, restic_collector, mock_subprocess_run, mock_stats_data):
        assert len(restic_collector.stats_cache) == 0
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b""
        )
        stats = restic_collector.get_stats("abc123")
        assert stats.total_size == 1073741824
        assert stats.total_file_count == 1000
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "stats",
            "--json",
            "abc123",
        ]
        assert mock_subprocess_run.call_count == 1
        assert len(restic_collector.stats_cache) == 1
        assert restic_collector.stats_cache["abc123"] == stats

        # Cached value (2nd call, value is cached, so no new subprocess call)
        stats = restic_collector.get_stats("abc123")
        assert stats.total_size == 1073741824
        assert stats.total_file_count == 1000
        assert mock_subprocess_run.call_count == 1

        # Error
        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"Error: snapshot not found")
        with pytest.raises(Exception, match="Error executing restic stats command"):
            restic_collector.get_stats("xyz222")
        assert mock_subprocess_run.call_count == 2

        # Insecure TLS
        restic_collector.insecure_tls = True
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json.dumps(mock_stats_data).encode("utf-8"), stderr=b""
        )
        stats = restic_collector.get_stats("xyz333")
        assert stats.total_size == 1073741824
        assert stats.total_file_count == 1000
        assert mock_subprocess_run.call_args[0][0] == [
            "restic",
            "--no-lock",
            "stats",
            "--json",
            "xyz333",
            "--insecure-tls",
        ]
        assert mock_subprocess_run.call_count == 3
        assert len(restic_collector.stats_cache) == 2

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
        # Restic >= 14: '2023-01-12T06:59:33.1576588+01:00'
        snapshot = {"time": "2023-01-12T06:59:33.1576588+01:00"}
        assert ResticCollector.calc_snapshot_timestamp(snapshot) == 1673503173.0

        # Restic 12: '2023-02-01T14:14:19.30760523Z'
        snapshot["time"] = "2023-02-01T14:14:19.30760523Z"
        assert ResticCollector.calc_snapshot_timestamp(snapshot) == 1675257259.0

    def test_parse_stderr(self):
        mock_result = MagicMock()
        mock_result.stderr = b"Error: repository not found\n"
        mock_result.returncode = 1

        result = ResticCollector.parse_stderr(mock_result)
        assert result == "Error: repository not found  Exit code: 1"


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
        assert collector.disable_stats is False
        assert collector.disable_locks is False
        assert collector.include_paths is False
        assert collector.insecure_tls is False
        # The collector has metrics after first refresh
        assert collector.metrics is not None
        assert len(collector.stats_cache) > 1

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
            "NO_STATS": "True",
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
        assert collector.disable_stats is True
        assert collector.disable_locks is True
        assert collector.include_paths is True
        assert collector.insecure_tls is True
        # The collector has metrics after first refresh
        assert collector.metrics is not None
        assert len(collector.stats_cache) == 0

        # Server starts
        mock_start_server.assert_called_once_with(8002, "127.0.0.1")

    @patch("exporter.exporter.start_http_server")
    @patch("exporter.exporter.REGISTRY.register")
    @patch("sys.exit")
    def test_main_error(self, mock_sys_exit, _mock_register, _mock_start_server, mock_restic_cli, caplog):
        caplog.set_level(logging.ERROR)

        main(refresh_loop=False)
        assert mock_sys_exit.call_count == 2
        assert "The environment variable RESTIC_REPOSITORY is mandatory" in caplog.messages
        assert (
            "One of the environment variables RESTIC_PASSWORD, RESTIC_PASSWORD_FILE or "
            "RESTIC_PASSWORD_COMMAND is mandatory"
        ) in caplog.messages
