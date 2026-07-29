"""Provider-neutral normalization and lineage helpers."""

from __future__ import annotations

import hashlib
import json
import re

from asharelens.data.models import Dataset

_CANONICAL_SYMBOL = re.compile(r"^(sh|sz|bj)\.(\d{6})$")
_TUSHARE_SYMBOL = re.compile(r"^(\d{6})\.(sh|sz|bj)$")
_PLAIN_SYMBOL = re.compile(r"^\d{6}$")


def normalize_a_share_symbol(raw: str) -> str:
    """Normalize supported Provider formats to `exchange.000000`."""

    value = raw.strip().lower()
    canonical_match = _CANONICAL_SYMBOL.fullmatch(value)
    if canonical_match is not None:
        explicit_exchange, code = canonical_match.groups()
    else:
        tushare_match = _TUSHARE_SYMBOL.fullmatch(value)
        if tushare_match is not None:
            code, explicit_exchange = tushare_match.groups()
        elif _PLAIN_SYMBOL.fullmatch(value) is not None:
            code = value
            explicit_exchange = None
        else:
            raise ValueError(f"unsupported A-share symbol: {raw!r}")

    inferred_exchange = _infer_exchange(code)
    if explicit_exchange is not None and explicit_exchange != inferred_exchange:
        raise ValueError(f"symbol exchange does not match A-share code: {raw!r}")
    return f"{inferred_exchange}.{code}"


def is_a_share_symbol(raw: str) -> bool:
    """Return whether a raw Provider code maps to a mainland A share."""

    try:
        normalize_a_share_symbol(raw)
    except ValueError:
        return False
    return True


def to_tushare_symbol(raw: str) -> str:
    """Convert any supported A-share code to Tushare's `000000.SH` form."""

    normalized = normalize_a_share_symbol(raw)
    exchange, code = normalized.split(".", maxsplit=1)
    return f"{code}.{exchange.upper()}"


def canonical_hash(value: object) -> str:
    """Hash JSON-compatible evidence independent of mapping insertion order."""

    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_source_batch_id(
    provider_id: str,
    dataset: Dataset,
    content_hash: str,
) -> str:
    """Build a readable bounded ID backed by the full stored content hash."""

    if len(content_hash) != 64:
        raise ValueError("content_hash must be a SHA-256 hex digest")
    return f"{provider_id}-{dataset.value}-{content_hash[:20]}"


def _infer_exchange(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    raise ValueError(f"unsupported mainland A-share code: {code!r}")
