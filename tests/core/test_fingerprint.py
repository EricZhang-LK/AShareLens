from asharelens.core.fingerprint import build_run_fingerprint


def test_fingerprint_is_canonical_for_parameter_key_order() -> None:
    first = build_run_fingerprint(
        "strategy-hash",
        {"slow": 60, "fast": 20},
        "snapshot-1",
        "engine-1",
    )
    second = build_run_fingerprint(
        "strategy-hash",
        {"fast": 20, "slow": 60},
        "snapshot-1",
        "engine-1",
    )

    assert first == second
    assert len(first) == 64


def test_fingerprint_changes_when_data_snapshot_changes() -> None:
    first = build_run_fingerprint("strategy-hash", {"fast": 20}, "snapshot-1", "engine-1")
    second = build_run_fingerprint("strategy-hash", {"fast": 20}, "snapshot-2", "engine-1")

    assert first != second
