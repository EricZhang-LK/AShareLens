"""Canonical fingerprints for reproducible strategy runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def build_run_fingerprint(
    strategy_code_hash: str,
    parameters: Mapping[str, object],
    data_snapshot_id: str,
    engine_version: str,
    run_config: Mapping[str, object] | None = None,
) -> str:
    """Hash every immutable input that can alter a core-only run."""

    payload = {
        "data_snapshot_id": data_snapshot_id,
        "engine_version": engine_version,
        "parameters": parameters,
        "run_config": run_config or {},
        "strategy_code_hash": strategy_code_hash,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
