from research_core.common import validate_data_manifest_record, validate_run_log_row


def test_discovery_manifest_cannot_be_oos_eligible():
    record = {
        "dataset_name": "eth",
        "symbol": "ETHUSDT",
        "timeframe": "1m",
        "path": "/tmp/x.csv",
        "start_utc": "2024-01-01",
        "end_utc": "2026-06-24",
        "row_count": 1,
        "sha256": "abc",
        "data_layer": "discovery",
        "oos_eligible": True,
        "notes": "seen",
    }
    assert validate_data_manifest_record(record) is False


def test_valid_discovery_manifest_record_has_required_fields():
    record = {
        "dataset_name": "eth",
        "symbol": "ETHUSDT",
        "timeframe": "1m",
        "path": "/tmp/x.csv",
        "start_utc": "2024-01-01",
        "end_utc": "2026-06-24",
        "row_count": 1,
        "sha256": "abc",
        "data_layer": "discovery",
        "oos_eligible": False,
        "notes": "seen",
    }
    assert validate_data_manifest_record(record) is True


def test_run_log_requires_hashes_and_data_layer():
    row = {
        "config_hash": "cfg",
        "data_hash": "data",
        "git_commit": "commit",
        "run_timestamp": "2026-06-25T00:00:00Z",
        "random_seed": 20260624,
        "data_layer": "discovery",
    }
    assert validate_run_log_row(row) is True
    row["data_hash"] = ""
    assert validate_run_log_row(row) is False

