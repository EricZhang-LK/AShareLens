from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from asharelens.data.models import (
    DataBatch,
    Dataset,
    Exchange,
    Instrument,
)
from asharelens.data.provider import ProviderError, ProviderMetadata


def test_data_batch_rejects_naive_fetch_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        DataBatch[Instrument](
            dataset=Dataset.INSTRUMENTS,
            provider_id="fixture",
            provider_version="1.0",
            fetched_at=datetime(2026, 7, 29, 18, 0),
            request={"as_of": "2026-07-29"},
            source_batch_id="batch-1",
            content_hash="a" * 64,
            records=(),
        )


def test_data_batch_preserves_lineage_and_request_metadata() -> None:
    batch = DataBatch[Instrument](
        dataset=Dataset.INSTRUMENTS,
        provider_id="fixture",
        provider_version="1.0",
        fetched_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        request={"as_of": "2026-07-29"},
        source_batch_id="batch-1",
        content_hash="a" * 64,
        records=(
            Instrument(
                symbol="sh.600000",
                name="浦发银行",
                listed_on=date(1999, 11, 10),
            ),
        ),
    )

    assert batch.provider_id == "fixture"
    assert batch.request == {"as_of": "2026-07-29"}
    assert batch.records[0].symbol == "sh.600000"


@pytest.mark.parametrize(
    ("symbol", "exchange"),
    [
        ("sh.600000", Exchange.SHANGHAI),
        ("sz.000001", Exchange.SHENZHEN),
        ("bj.430047", Exchange.BEIJING),
    ],
)
def test_instrument_accepts_normalized_a_share_symbols(
    symbol: str,
    exchange: Exchange,
) -> None:
    instrument = Instrument(symbol=symbol, name="测试股票")

    assert instrument.exchange is exchange


def test_provider_metadata_schema_exposes_plugin_api_version() -> None:
    schema = ProviderMetadata.model_json_schema()

    assert schema["properties"]["plugin_api_version"]["type"] == "string"


def test_provider_error_exposes_stable_diagnostic_fields() -> None:
    error = ProviderError(
        provider_id="fixture",
        error_code="upstream_timeout",
        message="provider did not respond",
        retryable=True,
    )

    assert error.provider_id == "fixture"
    assert error.error_code == "upstream_timeout"
    assert error.retryable is True
    assert str(error) == "provider did not respond"
