import pytest

from asharelens.data.models import Dataset
from asharelens.data.providers.common import (
    build_source_batch_id,
    canonical_hash,
    normalize_a_share_symbol,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600000", "sh.600000"),
        ("600000.SH", "sh.600000"),
        ("sh.600000", "sh.600000"),
        ("000001", "sz.000001"),
        ("000001.SZ", "sz.000001"),
        ("430047", "bj.430047"),
        ("920001.BJ", "bj.920001"),
    ],
)
def test_normalize_a_share_symbol_supports_provider_formats(
    raw: str,
    expected: str,
) -> None:
    assert normalize_a_share_symbol(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "510300",
        "000001.SH",
        "600000.SZ",
        "ABCDEF",
        "600000.HK",
    ],
)
def test_normalize_a_share_symbol_rejects_non_a_share_codes(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_a_share_symbol(raw)


def test_canonical_hash_is_order_independent_and_source_id_is_bounded() -> None:
    first = canonical_hash({"request": {"b": 2, "a": 1}, "rows": [{"x": 3}]})
    second = canonical_hash({"rows": [{"x": 3}], "request": {"a": 1, "b": 2}})

    assert first == second
    assert len(first) == 64
    source_id = build_source_batch_id("a-provider", Dataset.DAILY_BARS, first)
    assert source_id == f"a-provider-daily_bars-{first[:20]}"
    assert len(source_id) <= 128
