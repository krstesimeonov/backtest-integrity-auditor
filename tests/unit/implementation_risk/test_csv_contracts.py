from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import replace

import pytest

from backtest_auditor.implementation_risk import (
    CanonicalRunArtifacts,
    TradeDirection,
    TradeRecord,
)
from backtest_auditor.implementation_risk.adapters.csv_contracts import (
    CASH_BALANCES,
    CASH_MOVEMENTS,
    COSTS,
    EQUITY,
    FILLS,
    MARKET_DATA,
    ORDERS,
    POSITIONS,
    RETURNS,
    SIGNALS,
    TRADES,
    TRADE_FILLS_FILE,
    decode_csv,
    decode_trade_fills,
    encode_csv,
    encode_trade_fills,
)
from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
)


def test_every_csv_contract_round_trips_canonical_records(
    canonical_file_bundle: CanonicalRunArtifacts,
) -> None:
    cash = canonical_file_bundle.cash
    assert cash is not None
    series = (
        (MARKET_DATA, canonical_file_bundle.market_data),
        (SIGNALS, canonical_file_bundle.signals),
        (ORDERS, canonical_file_bundle.orders),
        (FILLS, canonical_file_bundle.fills),
        (TRADES, canonical_file_bundle.trades),
        (POSITIONS, canonical_file_bundle.positions),
        (CASH_BALANCES, cash.balances),
        (CASH_MOVEMENTS, cash.movements),
        (COSTS, canonical_file_bundle.costs),
        (EQUITY, canonical_file_bundle.equity),
        (RETURNS, canonical_file_bundle.returns),
    )

    for contract, records in series:
        assert records is not None
        encoded = encode_csv(contract, records)
        expected = records
        if contract is TRADES:
            expected = tuple(replace(record, fill_ids=()) for record in records)
        assert decode_csv(contract, encoded) == expected
        assert encoded.endswith(b"\n")


def test_header_only_csv_round_trips_as_available_empty() -> None:
    encoded = encode_csv(SIGNALS, ())

    assert decode_csv(SIGNALS, encoded) == ()
    assert (
        encoded
        == b"signal_id,timestamp,instrument_id,signal_type,value,source_data_timestamp\n"
    )


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"\xff", BundleErrorCode.INVALID_ROW),
        (b"bad,header\n", BundleErrorCode.HEADER_MISMATCH),
        (
            b"signal_id,timestamp,instrument_id,signal_type,value,source_data_timestamp\r\n",
            BundleErrorCode.INVALID_ROW,
        ),
        (
            b"signal_id,timestamp,instrument_id,signal_type,value,source_data_timestamp\n"
            b"signal-1,not-time,AAPL.XNAS,target_quantity,10,\n",
            BundleErrorCode.INVALID_ROW,
        ),
        (
            b"signal_id,timestamp,instrument_id,signal_type,value,source_data_timestamp\n"
            b"signal-1,2026-01-01T00:00:00Z,AAPL.XNAS,target_quantity,10,\n",
            BundleErrorCode.INVALID_ROW,
        ),
        (
            b"signal_id,timestamp,instrument_id,signal_type,value,source_data_timestamp\n"
            b"signal-1,2026-01-01T00:00:00.000000Z,AAPL.XNAS,target_quantity,10,,extra\n",
            BundleErrorCode.INVALID_ROW,
        ),
    ],
)
def test_csv_decoder_rejects_invalid_or_noncanonical_bytes(data, code) -> None:
    with pytest.raises(BundleContractError) as captured:
        decode_csv(SIGNALS, data)

    assert captured.value.code is code
    assert captured.value.file_path == SIGNALS.file_name


def test_trade_fill_link_contract_is_normalized_and_round_trips() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = (
        TradeRecord(
            "trade-b",
            "AAPL.XNAS",
            TradeDirection.LONG,
            timestamp,
            Decimal(1),
            Decimal(1),
            "USD",
            "test",
            fill_ids=("fill-b", "fill-a"),
        ),
        TradeRecord(
            "trade-a",
            "AAPL.XNAS",
            TradeDirection.LONG,
            timestamp,
            Decimal(1),
            Decimal(1),
            "USD",
            "test",
            fill_ids=("fill-c",),
        ),
    )

    encoded = encode_trade_fills(trades)

    assert encoded == (
        b"trade_id,fill_id\ntrade-a,fill-c\ntrade-b,fill-a\ntrade-b,fill-b\n"
    )
    assert decode_trade_fills(encoded) == (
        ("trade-a", "fill-c"),
        ("trade-b", "fill-a"),
        ("trade-b", "fill-b"),
    )


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", BundleErrorCode.HEADER_MISMATCH),
        (b"wrong,header\n", BundleErrorCode.HEADER_MISMATCH),
        (b"trade_id,fill_id\na,\n", BundleErrorCode.INVALID_ROW),
        (
            b"trade_id,fill_id\na,b\na,b\n",
            BundleErrorCode.INVALID_ROW,
        ),
        (
            b"trade_id,fill_id\nb,b\na,a\n",
            BundleErrorCode.INVALID_ROW,
        ),
        (
            b'trade_id,fill_id\n"a",b\n',
            BundleErrorCode.INVALID_ROW,
        ),
        (b"\xff", BundleErrorCode.INVALID_ROW),
    ],
)
def test_trade_fill_decoder_rejects_invalid_contract(data, code) -> None:
    with pytest.raises(BundleContractError) as captured:
        decode_trade_fills(data)

    assert captured.value.code is code
    assert captured.value.file_path == TRADE_FILLS_FILE
