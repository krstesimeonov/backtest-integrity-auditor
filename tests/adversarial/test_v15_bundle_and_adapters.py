"""Adversarial contract tests for the V1.5 canonical bundle and engine adapters.

Scope (package ``backtest-integrity-auditor`` 1.5.0, import ``backtest_auditor``):

1. Canonical artifact bundle 1.0 round trip (docs/V1_5C_FILE_BUNDLE_CONTRACT.md,
   docs/adr/ADR-003-V1_5_HYBRID_FILE_BUNDLE.md).
2. Bundle reader/writer rejection of missing required manifest/specification
   keys (schemas canonical-artifact-bundle-manifest-1.0 and
   canonical-run-specification-1.0).
3. Each of the five engine adapters rejecting an export with a missing required
   column/field (docs/V1_5D1_SHARED_ADAPTER_FOUNDATION.md "Fatal failures versus
   warnings", docs/V1_5D2_*.md / docs/V1_5D3_*.md "File contracts").
4. Each adapter mapping one synthetic engine run to the documented canonical
   artifacts (docs/V1_5D2_*.md "Engine semantics", docs/V1_5D3_*.md workflow
   sections, docs/V1_5D1_*.md "Output invariants").

All expected values are derived from the synthetic inputs built in this file
and from the documents above -- never copied from the package's own tests or
examples.  Engine SDKs (vectorbt, bt, backtrader, nautilus_trader, LEAN) are
neither installed nor needed: the documented mapping path is file-only.

This module deliberately uses nothing from ``tests/adversarial/conftest.py``.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from backtest_auditor.implementation_risk.adapters.canonical_bundle import (
    BUNDLE_SCHEMA_VERSION,
    CanonicalArtifactFileBundleAdapter,
)
from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
)
from backtest_auditor.implementation_risk.application.d3 import build_v1_5d3_service
from backtest_auditor.implementation_risk.application.errors import (
    EngineAdapterError,
    EngineAdapterErrorCode,
)
from backtest_auditor.implementation_risk.domain import (
    ArtifactReturnConvention,
    AssetClass,
    CanonicalParameter,
    CanonicalRunArtifacts,
    CanonicalRunSpecification,
    CashArtifacts,
    CashBalance,
    CashMovement,
    CashMovementType,
    ComparisonLevel,
    CostRecord,
    CostType,
    EngineRunReference,
    EquityPoint,
    FillRecord,
    InstrumentReference,
    LiquidityRole,
    MarketDataObservation,
    ModelSpecification,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    ReturnPoint,
    SignalRecord,
    SignalType,
    SimulationSpecification,
    StrategySpecification,
    TimeInForce,
    TradeDirection,
    TradeRecord,
)


# ---------------------------------------------------------------------------
# Independent helpers (canonical encodings as documented, not the package's).
# ---------------------------------------------------------------------------

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
PST = timezone(timedelta(hours=-8))

LEVEL_ORDER = (
    "strategy_specification",
    "market_data",
    "signal",
    "order",
    "fill",
    "trade",
    "position",
    "cash",
    "cost",
    "equity",
    "return",
)

# V1_5C "Bundle layout" table: which files back which level.
LEVEL_FILES = {
    "strategy_specification": ("specification.json",),
    "market_data": ("market_data.csv",),
    "signal": ("signals.csv",),
    "order": ("orders.csv",),
    "fill": ("fills.csv",),
    "trade": ("trade_fills.csv", "trades.csv"),
    "position": ("positions.csv",),
    "cash": ("cash_balances.csv", "cash_movements.csv"),
    "cost": ("costs.csv",),
    "equity": ("equity.csv",),
    "return": ("returns.csv",),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    """V1_5C "Canonical JSON rules": UTF-8, 2-space indent, sorted keys, final LF."""

    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _compact_json(value: object) -> bytes:
    """V1_5C "Manifest 1.0": identity uses canonical compact JSON."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _csv_bytes(headers: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    """V1_5C/D2 CSV rules: comma, minimal quoting, LF, final newline, UTF-8."""

    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def _ts(text: str) -> datetime:
    """Parse ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` into an aware UTC datetime."""

    assert text.endswith("Z")
    return datetime.fromisoformat(text[:-1] + "+00:00")


def _load_schema(file_name: str) -> dict[str, Any]:
    root = resources.files("backtest_auditor.implementation_risk") / "schemas"
    return json.loads((root / file_name).read_text(encoding="utf-8"))


MANIFEST_SCHEMA = _load_schema("canonical-artifact-bundle-manifest-1.0.schema.json")
SPEC_SCHEMA = _load_schema("canonical-run-specification-1.0.schema.json")
ENVELOPE_SCHEMA = _load_schema("engine-export-envelope-1.0.schema.json")
METADATA_SCHEMA = _load_schema("engine-adapter-metadata-1.0.schema.json")


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        name = node["$ref"].split("/")[-1]
        node = schema["$defs"][name]
    return node


def _allows_null(schema: dict[str, Any], node: dict[str, Any]) -> bool:
    node = _resolve(schema, node)
    if node.get("type") == "null":
        return True
    return any(_allows_null(schema, item) for item in node.get("oneOf", ()))


def _assert_identical(left: object, right: object, path: str = "bundle") -> None:
    """Field-by-field, type-exact comparison (bit-for-bit for Decimal).

    Plain ``==`` is not enough: ``True == 1 == Decimal(1)`` and
    ``Decimal('1.0') == Decimal('1')``; timestamps must also stay UTC-aware.
    """

    assert type(left) is type(right), f"{path}: {type(left)!r} != {type(right)!r}"
    if dataclasses.is_dataclass(left):
        for item in dataclasses.fields(left):
            _assert_identical(
                getattr(left, item.name),
                getattr(right, item.name),
                f"{path}.{item.name}",
            )
    elif isinstance(left, tuple):
        assert len(left) == len(right), f"{path}: length {len(left)} != {len(right)}"
        for index, (a, b) in enumerate(zip(left, right)):
            _assert_identical(a, b, f"{path}[{index}]")
    elif isinstance(left, Decimal):
        assert left.as_tuple() == right.as_tuple(), f"{path}: {left!r} != {right!r}"
    elif isinstance(left, datetime):
        assert left == right, f"{path}: {left!r} != {right!r}"
        assert left.utcoffset() == timedelta(0) == right.utcoffset(), path
    else:
        assert left == right, f"{path}: {left!r} != {right!r}"


# ---------------------------------------------------------------------------
# Test 1 data: a rich synthetic canonical bundle with adversarial values.
# ---------------------------------------------------------------------------

PRE_EPOCH = datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
T0 = datetime(2024, 2, 29, 9, 15, 0, 1, tzinfo=IST)  # 03:45:00.000001Z (leap day)
T1 = datetime(2024, 2, 29, 3, 0, 0, 999999, tzinfo=PST)  # 11:00:00.999999Z
T2 = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
T3 = datetime(2024, 3, 1, 12, 0, 0, 500000, tzinfo=UTC)
T4 = datetime(
    2024, 3, 2, 7, 0, 0, tzinfo=timezone(timedelta(hours=14))
)  # 2024-03-01T17:00Z

JP = "株式-7203"
SHA_A = "ab" * 32
SHA_B = "0123456789abcdef" * 4

# Adversarial decimals: beyond binary64 range, tiny, 28 significant digits.
TINY = Decimal("1E-30")
HUGE = Decimal("1E+400")
WIDE = Decimal("-1234567890123456789.012345678")  # 28 significant digits


def _p(name: str, value: object, unit: str | None = None) -> CanonicalParameter:
    return CanonicalParameter(name=name, value=value, unit=unit)


def _rich_specification() -> CanonicalRunSpecification:
    universe = (
        InstrumentReference(
            instrument_id="AAPL",
            asset_class=AssetClass.EQUITY,
            symbol="AAPL",
            currency="USD",
            venue="XNAS",
            contract_multiplier=Decimal("1"),
            attributes=(_p("lot.size", 100, "shares"),),
        ),
        InstrumentReference(
            instrument_id=JP,
            asset_class=AssetClass.EQUITY,
            symbol="7203.T",
            currency="JPY",
            venue=None,
            contract_multiplier=Decimal("0.0001"),
            attributes=(),
        ),
    )
    strategy = StrategySpecification(
        strategy_id="strat-Ω",
        name="Mean réversion ✓   line-separator",
        logic_sha256=SHA_B,
        universe=universe,
        parameters=(
            _p("bool.true", True),
            _p("bool.false", False),
            _p("int.one", 1),
            _p("decimal.one", Decimal("1")),
            _p("int.big", 2**70),
            _p("int.negative", -7),
            _p("decimal.tiny", TINY),
            _p("decimal.huge", HUGE),
            _p("decimal.negative_zero", Decimal("-0")),
            _p("decimal.wide", WIDE),
            _p("explicit.null", None),
            _p("text.unicode", 'αβγ – “quoted”, comma "and quote"', unit="ünit\x85"),
        ),
        data_frequency="1min",
        signal_timing="bar close",
        signal_model=ModelSpecification(
            name="signal",
            parameters=(_p("window", 20, "bars"),),
            version="2.1",
            implementation_sha256=SHA_A,
        ),
        sizing_model=ModelSpecification(name="sizing"),
        version=None,
    )
    simulation = SimulationSpecification(
        base_currency="USD",
        initial_cash=Decimal("1000000.50"),
        calendar="XNYS",
        calendar_timezone="America/New_York",
        data_adjustment_policy="split-adjusted",
        execution_timing="next open",
        execution_model=ModelSpecification(name="execution"),
        accounting_model=ModelSpecification(name="accounting", version="1"),
        cost_models=(
            ModelSpecification(
                name="z-fee", parameters=(_p("bps", Decimal("0.5"), "bps"),)
            ),
            ModelSpecification(name="a-slippage"),
        ),
        shorting_allowed=True,
        fractional_quantity_allowed=False,
    )
    return CanonicalRunSpecification(strategy=strategy, simulation=simulation)


def _rich_bundle(*, engine_version: str | None) -> CanonicalRunArtifacts:
    run = EngineRunReference(
        run_id="run-Ωμέγα-ü",
        engine_name="synthetic-engine-ñ",
        engine_version=engine_version,
        source_sha256=SHA_A,
    )
    market_data = (
        MarketDataObservation(
            observation_id="md-1",
            instrument_id="AAPL",
            event_timestamp=PRE_EPOCH,
            field="close",
            value=TINY,
            available_timestamp=None,
            unit=None,
        ),
        MarketDataObservation(
            observation_id="md-2",
            instrument_id=JP,
            event_timestamp=T0,
            field="終値",
            value=WIDE,
            available_timestamp=T1,
            unit="JPY/share ",
        ),
    )
    signals = (
        SignalRecord("s-1", T0, "AAPL", SignalType.TARGET_WEIGHT, Decimal("-0.5"), T0),
        SignalRecord("s-2", T1, "AAPL", SignalType.ENTRY, None, None),
    )
    orders = (
        OrderRecord(
            order_id="o-1",
            created_at=T0,
            instrument_id="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            status=OrderStatus.FILLED,
            signal_id="s-1",
            submitted_at=T0,
            last_updated_at=T1,
        ),
        OrderRecord(
            order_id="o-2",
            created_at=T1,
            instrument_id="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("4"),
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.GTD,
            status=OrderStatus.PARTIALLY_FILLED,
            parent_order_id="o-1",
            submitted_at=T1,
            last_updated_at=T2,
            expires_at=T4,
            limit_price=Decimal("187.125"),
        ),
        OrderRecord(
            order_id="o-3",
            created_at=T2,
            instrument_id=JP,
            side=OrderSide.BUY,
            quantity=Decimal("0.0001"),
            order_type=OrderType.STOP_LIMIT,
            time_in_force=TimeInForce.GTC,
            status=OrderStatus.CREATED,
            limit_price=Decimal("2500"),
            stop_price=Decimal("2400"),
        ),
    )
    fills = (
        FillRecord(
            "f-1",
            "o-1",
            T1,
            "AAPL",
            OrderSide.BUY,
            Decimal("10"),
            Decimal("185.000001"),
            "USD",
            LiquidityRole.MAKER,
            None,
        ),
        FillRecord(
            "f-2",
            "o-2",
            T2,
            "AAPL",
            OrderSide.SELL,
            Decimal("1"),
            Decimal("187.125"),
            "USD",
            LiquidityRole.TAKER,
            "XNAS",
        ),
    )
    trades = (
        TradeRecord(
            trade_id="t-1",
            instrument_id="AAPL",
            direction=TradeDirection.LONG,
            opened_at=T1,
            quantity=Decimal("10"),
            entry_price=Decimal("185.000001"),
            currency="USD",
            grouping_method='fifo "strict", v2',
            closed_at=T3,
            exit_price=Decimal("187.125"),
            realized_pnl=Decimal("-0.000001"),
            fill_ids=("f-2", "f-1"),
        ),
        TradeRecord(
            trade_id="t-2",
            instrument_id=JP,
            direction=TradeDirection.SHORT,
            opened_at=T3,
            quantity=Decimal("1"),
            entry_price=Decimal("2400"),
            currency="JPY",
            grouping_method="lifo",
        ),
    )
    positions = (
        PositionSnapshot(
            T1,
            "AAPL",
            Decimal("10"),
            "USD",
            Decimal("185.5"),
            Decimal("1855"),
            Decimal("185.000001"),
            Decimal("0"),
            Decimal("4.99999"),
        ),
        PositionSnapshot(T3, JP, Decimal("-1"), "JPY"),
    )
    cash = CashArtifacts(
        balances=(
            CashBalance(T0, "USD", Decimal("1000000.5"), None),
            CashBalance(T1, "JPY", Decimal("0"), Decimal("0")),
            CashBalance(T1, "USD", Decimal("998149.49999"), Decimal("1000000.5")),
        ),
        movements=(
            CashMovement(
                "m-1", T0, "USD", Decimal("1000000.5"), CashMovementType.DEPOSIT, None
            ),
            CashMovement(
                "m-2", T2, "USD", Decimal("-0.37"), CashMovementType.BORROW_FEE, "o-2"
            ),
        ),
    )
    costs = (
        CostRecord(
            "c-1", T1, CostType.COMMISSION, Decimal("-1.25"), "USD", "o-1", "f-1", "t-1"
        ),
        CostRecord("c-2", T2, CostType.OTHER, Decimal("0.01"), "USD", None, None, None),
    )
    equity = (
        EquityPoint(
            T0,
            "USD",
            Decimal("1000000.5"),
            Decimal("1000000.5"),
            Decimal("0"),
            Decimal("0"),
        ),
        EquityPoint(
            T1, "USD", Decimal("1000001.7"), None, Decimal("1855"), Decimal("-1855")
        ),
    )
    returns = (
        ReturnPoint(T0, T1, Decimal("0.0000012"), ArtifactReturnConvention.SIMPLE),
        ReturnPoint(T1, T2, Decimal("-1"), ArtifactReturnConvention.SIMPLE),
        ReturnPoint(T2, T3, Decimal("-123.456"), ArtifactReturnConvention.LOG),
        ReturnPoint(T3, T4, TINY, ArtifactReturnConvention.LOG),
    )
    return CanonicalRunArtifacts(
        run=run,
        specification=_rich_specification(),
        market_data=market_data,
        signals=signals,
        orders=orders,
        fills=fills,
        trades=trades,
        positions=positions,
        cash=cash,
        costs=costs,
        equity=equity,
        returns=returns,
    )


def _sparse_bundle() -> CanonicalRunArtifacts:
    """Unavailable (None) levels mixed with available-but-empty (()) levels."""

    return CanonicalRunArtifacts(
        run=EngineRunReference(
            run_id="sparse",
            engine_name="synthetic",
            engine_version="9.9.9-β",
            source_sha256=SHA_B,
        ),
        signals=(),
        trades=(),
        cash=CashArtifacts(balances=None, movements=()),
        equity=(),
    )


def _read_bundle_files(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def _data_row_count(data: bytes) -> int:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
    return len(rows) - 1


def _assert_manifest_matches_disk(files: dict[str, bytes]) -> dict[str, Any]:
    """Independent verification of manifest identity, inventory, hashes, counts."""

    manifest_bytes = files["manifest.json"]
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    assert _canonical_json(manifest) == manifest_bytes, "manifest is not canonical JSON"
    assert manifest["bundle_schema_version"] == "1.0" == BUNDLE_SCHEMA_VERSION
    assert manifest["artifact_schema_version"] == "1.0"
    body = {
        key: value for key, value in manifest.items() if key != "bundle_content_sha256"
    }
    assert manifest["bundle_content_sha256"] == _sha256(_compact_json(body))

    entries = manifest["files"]
    paths = [entry["path"] for entry in entries]
    assert paths == sorted(paths)
    assert set(paths) == set(files) - {"manifest.json"}
    for entry in entries:
        data = files[entry["path"]]
        assert entry["sha256"] == _sha256(data), entry["path"]
        assert entry["size_bytes"] == len(data), entry["path"]
        if entry["path"].endswith(".json"):
            assert entry["media_type"] == "application/json"
            assert entry["record_count"] == 1
        else:
            assert entry["media_type"] == "text/csv; charset=utf-8"
            assert entry["record_count"] == _data_row_count(data), entry["path"]
            text = data.decode("utf-8")
            assert "\r" not in text and text.endswith("\n")
    declared = sorted(
        name for level in manifest["levels"].values() for name in level["files"]
    )
    assert declared == paths
    return manifest


# ---------------------------------------------------------------------------
# Test 1: canonical bundle 1.0 round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("container", ["directory", "zip"])
@pytest.mark.parametrize("engine_version", [None, "1.2.3-rc.1+βuild"])
def test_canonical_bundle_round_trip_preserves_every_field(
    tmp_path: Path, container: str, engine_version: str | None
) -> None:
    """Bundle 1.0 write->read preserves every field bit-for-bit.

    Contract: docs/V1_5C_FILE_BUNDLE_CONTRACT.md "Public API" (lines 30-55),
    "Manifest 1.0" (84-103: schema versions, SHA-256, byte size, record count,
    bundle_content_sha256 over canonical compact JSON), "Canonical JSON rules"
    (119-132: explicit null, decimals as strings), "Canonical CSV rules"
    (134-152: no exponent, UTC ``Z`` with six fractional digits), and
    docs/adr/ADR-003 "Consequences": "Exact Decimal and UTC semantics survive
    file exchange".  Adversarial values: non-UTC offsets, pre-epoch and leap-day
    timestamps, 1E-30 / 1E+400 / 28-significant-digit decimals, negative zero,
    bool-vs-int-vs-Decimal parameters, non-ASCII ids, U+2028/U+0085 text,
    CSV quoting characters, and explicitly-null optional fields.
    """

    bundle = _rich_bundle(engine_version=engine_version)
    adapter = CanonicalArtifactFileBundleAdapter()
    destination = tmp_path / ("bundle.zip" if container == "zip" else "bundle")
    written = adapter.write(bundle, destination)
    restored = adapter.read(written)

    _assert_identical(bundle, restored)
    assert restored == bundle
    assert restored.available_levels == tuple(ComparisonLevel)

    # Domain normalized every timestamp to UTC; the restored instants must be
    # identical to the original aware inputs (not shifted by the offset).
    assert restored.market_data[1].event_timestamp == T0
    assert (
        restored.market_data[1].event_timestamp.isoformat()
        == "2024-02-29T03:45:00.000001+00:00"
    )
    assert restored.orders[1].expires_at == T4
    assert restored.market_data[0].event_timestamp == PRE_EPOCH

    # Type-exact parameter values: bool/int/Decimal must not collapse.
    params = {
        item.name: item.value for item in restored.specification.strategy.parameters
    }
    assert type(params["bool.true"]) is bool and params["bool.true"] is True
    assert type(params["int.one"]) is int and params["int.one"] == 1
    assert type(params["decimal.one"]) is Decimal
    assert params["int.big"] == 2**70 and type(params["int.big"]) is int
    assert params["decimal.huge"].as_tuple() == HUGE.as_tuple()
    assert params["decimal.tiny"].as_tuple() == TINY.as_tuple()
    assert params["decimal.negative_zero"].as_tuple() == Decimal("0").as_tuple()
    assert params["explicit.null"] is None
    assert restored.run.engine_version == engine_version

    # Same logical identity before and after, and a re-write is byte-identical.
    assert adapter.content_sha256(restored) == adapter.content_sha256(bundle)
    if container == "directory":
        files = _read_bundle_files(written)
    else:
        import zipfile

        with zipfile.ZipFile(written) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    rewritten = adapter.write(restored, tmp_path / "rewritten")
    assert _read_bundle_files(rewritten) == files

    manifest = _assert_manifest_matches_disk(files)
    assert manifest["bundle_content_sha256"] == adapter.content_sha256(bundle)
    assert "engine_version" in manifest["run"]
    assert (
        manifest["run"]["engine_version"] == engine_version
    )  # explicit null when None
    assert manifest["run"] == {
        "engine_name": "synthetic-engine-ñ",
        "engine_version": engine_version,
        "run_id": "run-Ωμέγα-ü",
        "source_sha256": SHA_A,
    }
    for level in LEVEL_ORDER:
        assert manifest["levels"][level]["status"] == "available"
        assert manifest["levels"][level]["files"] == sorted(LEVEL_FILES[level])

    # Record counts derived from the synthetic input, not from the manifest.
    counts = {entry["path"]: entry["record_count"] for entry in manifest["files"]}
    assert counts == {
        "specification.json": 1,
        "market_data.csv": 2,
        "signals.csv": 2,
        "orders.csv": 3,
        "fills.csv": 2,
        "trades.csv": 2,
        "trade_fills.csv": 2,
        "positions.csv": 2,
        "cash_balances.csv": 3,
        "cash_movements.csv": 2,
        "costs.csv": 2,
        "equity.csv": 2,
        "returns.csv": 4,
    }

    # On-disk scalar spelling: no exponent, no "-0", UTC Z with 6 digits.
    returns_text = files["returns.csv"].decode("utf-8")
    assert "0.000000000000000000000000000001" in returns_text
    assert "E" not in returns_text and "e-" not in returns_text
    assert "2024-02-29T03:45:00.000001Z" in returns_text
    assert "2024-03-01T17:00:00.000000Z" in returns_text
    md_text = files["market_data.csv"].decode("utf-8")
    assert "1969-12-31T23:59:59.999999Z" in md_text
    assert "-1234567890123456789.012345678" in md_text
    spec = json.loads(files["specification.json"].decode("utf-8"))
    by_name = {item["name"]: item for item in spec["strategy"]["parameters"]}
    assert by_name["decimal.huge"] == {
        "name": "decimal.huge",
        "unit": None,
        "value_type": "decimal",
        "value": "1" + "0" * 400,
    }
    assert by_name["decimal.negative_zero"]["value"] == "0"
    assert by_name["explicit.null"] == {
        "name": "explicit.null",
        "unit": None,
        "value_type": "null",
        "value": None,
    }
    assert by_name["bool.true"]["value_type"] == "boolean"
    assert by_name["int.one"]["value_type"] == "integer"
    assert by_name["decimal.one"] == {
        "name": "decimal.one",
        "unit": None,
        "value_type": "decimal",
        "value": "1",
    }
    assert spec["strategy"]["version"] is None and "version" in spec["strategy"]
    assert spec["strategy"]["universe"][1]["venue"] is None
    trade_links = files["trade_fills.csv"].decode("utf-8")
    assert trade_links == "trade_id,fill_id\nt-1,f-1\nt-1,f-2\n"


def test_canonical_bundle_round_trip_keeps_unavailable_distinct_from_empty(
    tmp_path: Path,
) -> None:
    """``None`` levels have no file; ``()`` levels have a header-only CSV.

    Contract: docs/V1_5C_FILE_BUNDLE_CONTRACT.md "Missing versus empty
    evidence" (105-117) and "CSV headers" (154-169); docs/V1_5B "Canonical
    collections and missing evidence"; cash balances/movements are
    independently optional (ADR-003 "Decision").
    """

    bundle = _sparse_bundle()
    adapter = CanonicalArtifactFileBundleAdapter()
    written = adapter.write(bundle, tmp_path / "sparse")
    restored = adapter.read(written)
    _assert_identical(bundle, restored)
    assert restored.specification is None and restored.market_data is None
    assert restored.orders is None and restored.fills is None
    assert restored.signals == () and restored.trades == () and restored.equity == ()
    assert restored.cash is not None
    assert restored.cash.balances is None and restored.cash.movements == ()

    files = _read_bundle_files(written)
    manifest = _assert_manifest_matches_disk(files)
    assert set(files) == {
        "manifest.json",
        "signals.csv",
        "trades.csv",
        "trade_fills.csv",
        "cash_movements.csv",
        "equity.csv",
    }
    assert (
        files["signals.csv"]
        == b"signal_id,timestamp,instrument_id,signal_type,value,source_data_timestamp\n"
    )
    assert (
        files["equity.csv"]
        == b"timestamp,currency,total_equity,cash,gross_exposure,net_exposure\n"
    )
    assert files["trade_fills.csv"] == b"trade_id,fill_id\n"
    assert files["cash_movements.csv"] == (
        b"movement_id,timestamp,currency,amount,movement_type,related_artifact_id\n"
    )
    expected_available = {"signal", "trade", "cash", "equity"}
    for level in LEVEL_ORDER:
        status = manifest["levels"][level]["status"]
        if level in expected_available:
            assert status == "available", level
        else:
            assert (
                status == "unavailable" and manifest["levels"][level]["files"] == []
            ), level
    assert manifest["levels"]["cash"]["files"] == ["cash_movements.csv"]
    assert all(entry["record_count"] == 0 for entry in manifest["files"])
    assert manifest["run"]["engine_version"] == "9.9.9-β"


def test_canonical_bundle_does_not_silently_round_high_precision_decimal(
    tmp_path: Path,
) -> None:
    """A 30-significant-digit Decimal is preserved exactly or rejected, never rounded.

    Contract: docs/V1_5B_CANONICAL_CONTRACTS.md "Numeric and time rules"
    (Decimal is used so representation cannot drift), docs/adr/ADR-003
    "Consequences" ("Exact Decimal ... semantics survive file exchange"), and
    docs/V1_5C_FILE_BUNDLE_CONTRACT.md:187 ("Validation does not ... repair
    ... evidence").  Realistic trigger: 18-decimal crypto quantities/balances
    with a 12-digit integer part.
    """

    value = Decimal("123456789012.123456789012345678")
    try:
        point = EquityPoint(T2, "USD", value)
    except ValueError:
        return  # explicit rejection satisfies the contract
    bundle = CanonicalRunArtifacts(
        run=EngineRunReference("precision", "synthetic", None, SHA_A), equity=(point,)
    )
    adapter = CanonicalArtifactFileBundleAdapter()
    restored = adapter.read(adapter.write(bundle, tmp_path / "precision"))
    assert restored.equity[0].total_equity == value, (
        f"stored {restored.equity[0].total_equity!r}, supplied {value!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: missing required keys in manifest/specification.
# ---------------------------------------------------------------------------


def _get(container: Any, path: tuple[Any, ...]) -> Any:
    for key in path:
        container = container[key]
    return container


def _manifest_cases() -> list[tuple[tuple[Any, ...], str]]:
    schema = MANIFEST_SCHEMA
    cases: list[tuple[tuple[Any, ...], str]] = []
    cases += [((), key) for key in schema["required"]]
    cases += [(("run",), key) for key in schema["properties"]["run"]["required"]]
    cases += [(("levels",), key) for key in schema["properties"]["levels"]["required"]]
    available = _resolve(schema, schema["properties"]["levels"]["properties"]["equity"])
    available_shape = [_resolve(schema, item) for item in available["oneOf"]][1]
    cases += [(("levels", "equity"), key) for key in available_shape["required"]]
    unavailable = schema["$defs"]["unavailableLevel"]
    cases += [(("levels", "market_data"), key) for key in unavailable["required"]]
    cases += [(("files", 0), key) for key in schema["$defs"]["file"]["required"]]
    return cases


def _spec_cases() -> list[tuple[tuple[Any, ...], str]]:
    schema = SPEC_SCHEMA
    defs = schema["$defs"]
    cases: list[tuple[tuple[Any, ...], str]] = []
    cases += [((), key) for key in schema["required"]]
    cases += [(("strategy",), key) for key in defs["strategy"]["required"]]
    cases += [(("simulation",), key) for key in defs["simulation"]["required"]]
    cases += [(("strategy", "signal_model"), key) for key in defs["model"]["required"]]
    cases += [
        (("strategy", "universe", 0), key) for key in defs["instrument"]["required"]
    ]
    cases += [
        (("strategy", "parameters", 0), key) for key in defs["parameter"]["required"]
    ]
    return cases


def _case_id(case: tuple[tuple[Any, ...], str]) -> str:
    path, key = case
    return ".".join(str(item) for item in (*path, key))


def _write_valid_bundle_for_mutation(tmp_path: Path) -> Path:
    bundle = dataclasses.replace(_rich_bundle(engine_version="1.0"), market_data=None)
    return CanonicalArtifactFileBundleAdapter().write(bundle, tmp_path / "valid")


def _reseal_manifest(manifest: dict[str, Any]) -> None:
    if "bundle_content_sha256" in manifest:
        body = {k: v for k, v in manifest.items() if k != "bundle_content_sha256"}
        manifest["bundle_content_sha256"] = _sha256(_compact_json(body))


@pytest.mark.parametrize("case", _manifest_cases(), ids=_case_id)
def test_bundle_reader_rejects_manifest_missing_required_key(
    tmp_path: Path, case: tuple[tuple[Any, ...], str]
) -> None:
    """Deleting any schema-``required`` manifest key yields a typed BundleContractError.

    Contract: canonical-artifact-bundle-manifest-1.0.schema.json ``required``
    lists (root, run, levels, level objects, file entries) and
    docs/V1_5C_FILE_BUNDLE_CONTRACT.md "Fail-closed validation" (171-189):
    ``BundleContractError`` with a stable code for an invalid manifest shape.
    The manifest is re-serialized canonically and its content identity is
    resealed so the missing key is the only defect.
    """

    path, key = case
    bundle_dir = _write_valid_bundle_for_mutation(tmp_path)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    target = _get(manifest, path)
    assert key in target, f"fixture lacks {_case_id(case)}"
    del target[key]
    _reseal_manifest(manifest)
    (bundle_dir / "manifest.json").write_bytes(_canonical_json(manifest))

    with pytest.raises(BundleContractError) as caught:
        CanonicalArtifactFileBundleAdapter().read(bundle_dir)
    assert caught.value.code in {
        BundleErrorCode.INVALID_MANIFEST,
        BundleErrorCode.UNSUPPORTED_SCHEMA_VERSION,
    }, str(caught.value)
    assert caught.value.file_path == "manifest.json"


@pytest.mark.parametrize("case", _spec_cases(), ids=_case_id)
def test_bundle_reader_rejects_specification_missing_required_key(
    tmp_path: Path, case: tuple[tuple[Any, ...], str]
) -> None:
    """Deleting any schema-``required`` specification key yields INVALID_SPECIFICATION.

    Contract: canonical-run-specification-1.0.schema.json ``required`` lists
    (root, strategy, simulation, model, instrument, parameter);
    docs/V1_5C_FILE_BUNDLE_CONTRACT.md "Canonical JSON rules" ("exact
    versioned fields", "explicit null for optional JSON fields") and
    "Fail-closed validation".  The specification file, its manifest entry
    (size/SHA-256) and the manifest identity are all resealed so the missing
    key is the only defect.
    """

    path, key = case
    bundle_dir = _write_valid_bundle_for_mutation(tmp_path)
    spec = json.loads((bundle_dir / "specification.json").read_text(encoding="utf-8"))
    target = _get(spec, path)
    assert key in target, f"fixture lacks {_case_id(case)}"
    del target[key]
    spec_bytes = _canonical_json(spec)
    (bundle_dir / "specification.json").write_bytes(spec_bytes)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "specification.json":
            entry["sha256"] = _sha256(spec_bytes)
            entry["size_bytes"] = len(spec_bytes)
    _reseal_manifest(manifest)
    (bundle_dir / "manifest.json").write_bytes(_canonical_json(manifest))

    with pytest.raises(BundleContractError) as caught:
        CanonicalArtifactFileBundleAdapter().read(bundle_dir)
    assert caught.value.code is BundleErrorCode.INVALID_SPECIFICATION, str(caught.value)
    assert caught.value.file_path == "specification.json"


def _non_nullable_required(schema: dict[str, Any], node: dict[str, Any]) -> list[str]:
    node = _resolve(schema, node)
    return [
        key
        for key in node["required"]
        if not _allows_null(schema, node["properties"][key])
    ]


_RUN_KWARGS = {
    "run_id": "r",
    "engine_name": "e",
    "engine_version": None,
    "source_sha256": SHA_A,
}


@pytest.mark.parametrize(
    "key",
    _non_nullable_required(MANIFEST_SCHEMA, MANIFEST_SCHEMA["properties"]["run"]),
)
def test_bundle_writer_cannot_receive_run_missing_required_value(
    tmp_path: Path, key: str
) -> None:
    """A run reference lacking a non-nullable required value never reaches the writer.

    Contract: manifest schema ``run.required`` (engine_name, run_id,
    source_sha256 are non-nullable; engine_version is required-but-nullable),
    docs/V1_5B "Numeric and time rules"/scope docstring (domain rejects
    invalid identity), docs/V1_5C "Public API" (writer accepts
    ``CanonicalRunArtifacts`` only) and "Fail-closed validation".
    """

    kwargs = dict(_RUN_KWARGS, **{key: None})
    with pytest.raises(ValueError):
        EngineRunReference(**kwargs)
    # A duck-typed object missing the value must be refused with a typed error
    # and must not leave anything on disk.
    fake = SimpleNamespace(run=SimpleNamespace(**kwargs), specification=None)
    destination = tmp_path / "never-written"
    with pytest.raises(BundleContractError) as caught:
        CanonicalArtifactFileBundleAdapter().write(fake, destination)  # type: ignore[arg-type]
    assert caught.value.code is BundleErrorCode.DOMAIN_VALIDATION_FAILED
    assert not destination.exists()
    with pytest.raises(ValueError):
        CanonicalRunArtifacts(run=None)  # type: ignore[arg-type]


def _spec_kwargs() -> dict[str, dict[str, Any]]:
    spec = _rich_specification()
    return {
        "strategy": {
            f.name: getattr(spec.strategy, f.name)
            for f in dataclasses.fields(spec.strategy)
        },
        "simulation": {
            f.name: getattr(spec.simulation, f.name)
            for f in dataclasses.fields(spec.simulation)
        },
    }


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("strategy", key)
        for key in _non_nullable_required(SPEC_SCHEMA, SPEC_SCHEMA["$defs"]["strategy"])
    ]
    + [
        ("simulation", key)
        for key in _non_nullable_required(
            SPEC_SCHEMA, SPEC_SCHEMA["$defs"]["simulation"]
        )
    ],
)
def test_specification_missing_required_value_is_rejected_before_writing(
    section: str, key: str
) -> None:
    """Every non-nullable required specification value set to None raises ValueError.

    Contract: canonical-run-specification-1.0.schema.json ``required`` minus
    nullable members, docs/V1_5B_CANONICAL_CONTRACTS.md "Specification
    contracts" (domain objects are validated at construction), and the
    package convention that domain contract failures are ``ValueError``
    (not ``TypeError``/``AttributeError`` leaks).
    """

    kwargs = _spec_kwargs()[section]
    kwargs[key] = None
    constructor = (
        StrategySpecification if section == "strategy" else SimulationSpecification
    )
    with pytest.raises(ValueError):
        constructor(**kwargs)


# ---------------------------------------------------------------------------
# Engine-export builder (independent implementation of the D1 envelope).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CsvPayload:
    role: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def as_bytes(self) -> bytes:
        return _csv_bytes(
            self.headers, [dict(zip(self.headers, row)) for row in self.rows]
        )


@dataclass(frozen=True)
class EngineCase:
    engine: str
    engine_version: str
    format_id: str
    base_currency: str
    levels: tuple[str, ...]
    payloads: dict[str, CsvPayload]
    run_id: str = field(default="adv-run-1")


def _write_engine_export(
    destination: Path,
    case: EngineCase,
    *,
    payload_override: dict[str, bytes] | None = None,
    metadata: dict[str, Any] | None = None,
    envelope_mutator: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Write ``engine-export.json`` + payloads exactly as docs/V1_5D1 describes."""

    destination.mkdir(parents=True)
    contents: dict[str, tuple[str, str, bytes]] = {}
    meta = (
        metadata
        if metadata is not None
        else {
            "adapter_export_schema_version": "1.0",
            "base_currency": case.base_currency,
        }
    )
    contents["adapter-metadata.json"] = (
        "adapter_metadata",
        "application/json",
        _canonical_json(meta),
    )
    for path, payload in case.payloads.items():
        data = payload.as_bytes()
        if payload_override and path in payload_override:
            data = payload_override[path]
        contents[path] = (payload.role, "text/csv", data)
    files = []
    for path in sorted(contents):
        role, media_type, data = contents[path]
        (destination / path).write_bytes(data)
        files.append(
            {
                "media_type": media_type,
                "path": path,
                "role": role,
                "sha256": _sha256(data),
                "size_bytes": len(data),
            }
        )
    body = {
        "declared_levels": [level for level in LEVEL_ORDER if level in case.levels],
        "engine": case.engine,
        "engine_version": case.engine_version,
        "envelope_schema_version": "1.0",
        "export_format_id": case.format_id,
        "export_format_version": "1.0",
        "files": files,
        "run_id": case.run_id,
    }
    envelope = {**body, "source_sha256": _sha256(_compact_json(body))}
    if envelope_mutator is not None:
        envelope_mutator(envelope)
    (destination / "engine-export.json").write_bytes(_canonical_json(envelope))
    return envelope


def _adapt(tmp_path: Path, case: EngineCase, name: str = "export", **kwargs: Any):
    directory = tmp_path / name
    envelope = _write_engine_export(directory, case, **kwargs)
    return envelope, build_v1_5d3_service().adapt(directory)


def _assert_common_result(
    tmp_path: Path, case: EngineCase, envelope: dict[str, Any], result: Any
) -> None:
    """Shared D1 output invariants plus independent hash verification."""

    run = result.artifacts.run
    assert run.run_id == case.run_id
    assert run.engine_name == case.engine
    assert run.engine_version == case.engine_version
    assert run.source_sha256 == envelope["source_sha256"]
    assert result.export.source_sha256 == envelope["source_sha256"]
    assert result.export.engine_version == case.engine_version
    assert result.export.engine.value == case.engine
    assert result.descriptor.engine.value == case.engine
    assert tuple(level.value for level in result.artifacts.available_levels) == tuple(
        level for level in LEVEL_ORDER if level in case.levels
    )
    adapter = CanonicalArtifactFileBundleAdapter()
    assert result.canonical_bundle_sha256 == adapter.content_sha256(result.artifacts)
    written = adapter.write(result.artifacts, tmp_path / f"{case.engine}-canonical")
    files = _read_bundle_files(written)
    manifest = _assert_manifest_matches_disk(files)
    assert manifest["bundle_content_sha256"] == result.canonical_bundle_sha256
    assert manifest["run"] == {
        "engine_name": case.engine,
        "engine_version": case.engine_version,
        "run_id": case.run_id,
        "source_sha256": envelope["source_sha256"],
    }
    _assert_identical(
        result.artifacts, adapter.read(written), f"{case.engine}.artifacts"
    )


def _same_records(
    actual: list[tuple[Any, ...]], expected: list[tuple[Any, ...]]
) -> None:
    """Exact multiset equality plus canonical (timestamp-first) ordering."""

    assert len(actual) == len(expected), f"{actual!r} != {expected!r}"
    assert sorted(actual, key=repr) == sorted(expected, key=repr), (
        f"{actual!r} != {expected!r}"
    )
    assert [item[0] for item in actual] == sorted(item[0] for item in expected)


D = Decimal

# --------------------------- vectorbt case ----------------------------------

VBT_I = "ÄPFEL.DE"
VBT_T = [
    "2026-03-02T14:30:00.123456Z",
    "2026-03-03T14:30:00.000000Z",
    "2026-03-04T14:30:00.000000Z",
    "2026-03-05T14:30:00.000000Z",
    "2026-03-06T14:30:00.000000Z",
    "2026-03-09T14:30:00.000001Z",
]
VBT_RETURNS = [
    "0.00475",
    "0.009952724558347848",
    "0.009854644986449864",
    "0.0219565747743352",
    "-0.0000954881356",
    "0.004774865",
]


def vectorbt_case() -> EngineCase:
    """vectorbt 1.1.0: buy 10 @50.5 (fee .25), sell 10 @55.25 (fee 0), short 5 @54."""

    t = VBT_T
    return EngineCase(
        engine="vectorbt",
        engine_version="1.1.0",
        format_id="backtest-auditor.vectorbt",
        base_currency="EUR",
        levels=(
            "order",
            "fill",
            "trade",
            "position",
            "cash",
            "cost",
            "equity",
            "return",
        ),
        payloads={
            "vectorbt-orders.csv": CsvPayload(
                "orders",
                (
                    "order_id",
                    "instrument",
                    "timestamp",
                    "size",
                    "price",
                    "fees",
                    "side",
                ),
                (
                    ("0", VBT_I, t[0], "10", "50.5", "0.25", "Buy"),
                    ("1", VBT_I, t[3], "10", "55.25", "0", "Sell"),
                    ("2", VBT_I, t[4], "5", "54", "0.1", "Sell"),
                ),
            ),
            "vectorbt-positions.csv": CsvPayload(
                "trades",
                (
                    "position_id",
                    "instrument",
                    "size",
                    "entry_timestamp",
                    "avg_entry_price",
                    "entry_fees",
                    "exit_timestamp",
                    "avg_exit_price",
                    "exit_fees",
                    "pnl",
                    "return",
                    "direction",
                    "status",
                ),
                (
                    (
                        "0",
                        VBT_I,
                        "10",
                        t[0],
                        "50.5",
                        "0.25",
                        t[3],
                        "55.25",
                        "0",
                        "47.25",
                        "0.0935643564356436",
                        "Long",
                        "Closed",
                    ),
                    (
                        "1",
                        VBT_I,
                        "5",
                        t[4],
                        "54",
                        "0.1",
                        t[5],
                        "53",
                        "0",
                        "4.9",
                        "0.0181481481481481",
                        "Short",
                        "Open",
                    ),
                ),
            ),
            "position-snapshots.csv": CsvPayload(
                "positions",
                ("timestamp", "instrument", "quantity", "market_price", "market_value"),
                (
                    (t[0], VBT_I, "10", "51", "510"),
                    (t[1], VBT_I, "10", "52", "520"),
                    (t[2], VBT_I, "10", "53", "530"),
                    (t[3], VBT_I, "0", "55.25", "0"),
                    (t[4], VBT_I, "-5", "54", "-270"),
                    (t[5], VBT_I, "-5", "53", "-265"),
                ),
            ),
            "portfolio-series.csv": CsvPayload(
                "portfolio",
                (
                    "timestamp",
                    "total_equity",
                    "cash",
                    "gross_exposure",
                    "net_exposure",
                    "return",
                ),
                (
                    (t[0], "1004.75", "494.75", "510", "510", VBT_RETURNS[0]),
                    (t[1], "1014.75", "494.75", "520", "520", VBT_RETURNS[1]),
                    (t[2], "1024.75", "494.75", "530", "530", VBT_RETURNS[2]),
                    (t[3], "1047.25", "1047.25", "0", "0", VBT_RETURNS[3]),
                    (t[4], "1047.15", "1317.15", "270", "-270", VBT_RETURNS[4]),
                    (t[5], "1052.15", "1317.15", "265", "-265", VBT_RETURNS[5]),
                ),
            ),
        },
    )


# ------------------------------ bt case -------------------------------------

BT_T = [
    "2026-04-01T00:00:00.000000Z",
    "2026-04-02T00:00:00.000000Z",
    "2026-04-03T00:00:00.000000Z",
    "2026-04-06T00:00:00.000000Z",
    "2026-04-07T00:00:00.000000Z",
]
BT_RETURNS = ["-0.00015", "0.0045006751012651898", "0.0051774779", "-0.000445743"]


def bt_case() -> EngineCase:
    """bt 1.2.0: two securities; signed transaction quantities; aggregate fees."""

    t = BT_T
    return EngineCase(
        engine="bt",
        engine_version="1.2.0",
        format_id="backtest-auditor.bt",
        base_currency="GBP",
        levels=("order", "fill", "position", "cash", "cost", "equity", "return"),
        payloads={
            "bt-transactions.csv": CsvPayload(
                "transactions",
                ("transaction_id", "timestamp", "instrument", "quantity", "price"),
                (
                    ("00000001", t[1], "AAA", "10", "100"),
                    ("00000002", t[1], "BBB", "5", "20"),
                    ("00000003", t[3], "AAA", "-4", "110"),
                ),
            ),
            "position-snapshots.csv": CsvPayload(
                "positions",
                ("timestamp", "instrument", "quantity", "market_price", "market_value"),
                (
                    (t[0], "AAA", "0", "", "0"),
                    (t[0], "BBB", "0", "", "0"),
                    (t[1], "AAA", "10", "100", "1000"),
                    (t[1], "BBB", "5", "20", "100"),
                    (t[2], "AAA", "10", "105", "1050"),
                    (t[2], "BBB", "5", "19", "95"),
                    (t[3], "AAA", "6", "110", "660"),
                    (t[3], "BBB", "5", "19.5", "97.5"),
                    (t[4], "AAA", "6", "108", "648"),
                    (t[4], "BBB", "5", "21", "105"),
                ),
            ),
            "portfolio-series.csv": CsvPayload(
                "portfolio",
                (
                    "timestamp",
                    "total_equity",
                    "cash",
                    "gross_exposure",
                    "net_exposure",
                    "fees",
                    "return",
                ),
                (
                    (t[0], "10000", "10000", "0", "0", "0", ""),
                    (t[1], "9998.5", "8898.5", "1100", "1100", "1.5", BT_RETURNS[0]),
                    (t[2], "10043.5", "8898.5", "1145", "1145", "0", BT_RETURNS[1]),
                    (t[3], "10095.5", "9338", "757.5", "757.5", "0.5", BT_RETURNS[2]),
                    (t[4], "10091", "9338", "753", "753", "0", BT_RETURNS[3]),
                ),
            ),
        },
    )


# --------------------------- Backtrader case --------------------------------

BTR_T = [
    "2026-05-04T13:30:00.000000Z",
    "2026-05-05T13:30:00.000000Z",
    "2026-05-06T13:30:00.000000Z",
    "2026-05-07T13:30:00.000000Z",
    "2026-05-08T13:30:00.000000Z",
    "2026-05-11T13:30:00.000000Z",
]
BTR_EQUITY = ["10000", "10100", "10605", "10074.75", "10074.75", "11082.225"]


def backtrader_case() -> EngineCase:
    """Backtrader 1.9.78.123: market/limit(GTD, partial)/stop(child, canceled) orders."""

    t = BTR_T
    return EngineCase(
        engine="backtrader",
        engine_version="1.9.78.123",
        format_id="backtest-auditor.backtrader",
        base_currency="USD",
        levels=("order", "fill", "position", "cash", "cost", "equity", "return"),
        payloads={
            "backtrader-orders.csv": CsvPayload(
                "orders",
                (
                    "order_ref",
                    "created_timestamp",
                    "submitted_timestamp",
                    "last_updated_timestamp",
                    "instrument",
                    "side",
                    "quantity",
                    "order_type",
                    "status",
                    "parent_order_ref",
                    "valid_timestamp",
                    "limit_price",
                    "stop_price",
                ),
                (
                    (
                        "1",
                        t[0],
                        t[1],
                        t[1],
                        "XYZ",
                        "Buy",
                        "10",
                        "Market",
                        "Completed",
                        "",
                        "",
                        "",
                        "",
                    ),
                    (
                        "2",
                        t[2],
                        t[2],
                        t[3],
                        "XYZ",
                        "Sell",
                        "4",
                        "Limit",
                        "Partial",
                        "",
                        t[5],
                        "120.5",
                        "",
                    ),
                    (
                        "3",
                        t[3],
                        t[3],
                        t[3],
                        "XYZ",
                        "Sell",
                        "1",
                        "Stop",
                        "Canceled",
                        "1",
                        "",
                        "",
                        "90",
                    ),
                ),
            ),
            "backtrader-fills.csv": CsvPayload(
                "fills",
                (
                    "fill_id",
                    "order_ref",
                    "timestamp",
                    "instrument",
                    "side",
                    "quantity",
                    "price",
                    "commission",
                ),
                (
                    ("1-1", "1", t[1], "XYZ", "Buy", "10", "101", "1.01"),
                    ("2-1", "2", t[3], "XYZ", "Sell", "2", "120.5", "0"),
                ),
            ),
            "position-snapshots.csv": CsvPayload(
                "positions",
                ("timestamp", "instrument", "quantity", "market_price", "market_value"),
                (
                    (t[0], "XYZ", "0", "100", "0"),
                    (t[1], "XYZ", "10", "101", "1010"),
                    (t[2], "XYZ", "10", "115", "1150"),
                    (t[3], "XYZ", "8", "121", "968"),
                    (t[4], "XYZ", "8", "119", "952"),
                    (t[5], "XYZ", "8", "130", "1040"),
                ),
            ),
            "portfolio-series.csv": CsvPayload(
                "portfolio",
                ("timestamp", "total_equity", "cash", "gross_exposure", "net_exposure"),
                (
                    (t[0], BTR_EQUITY[0], "10000", "0", "0"),
                    (t[1], BTR_EQUITY[1], "8988.99", "1010", "1010"),
                    (t[2], BTR_EQUITY[2], "8988.99", "1150", "1150"),
                    (t[3], BTR_EQUITY[3], "9229.99", "968", "968"),
                    (t[4], BTR_EQUITY[4], "9229.99", "952", "952"),
                    (t[5], BTR_EQUITY[5], "9229.99", "1040", "1040"),
                ),
            ),
        },
    )


# ------------------------ QuantConnect LEAN case ----------------------------

LEAN_T = [
    "2026-06-01T13:30:00.000000Z",
    "2026-06-01T13:31:00.250000Z",
    "2026-06-02T13:30:00.000000Z",
    "2026-06-02T15:00:00.000000Z",
    "2026-06-03T13:30:00.000000Z",
]
LEAN_EQUITY = ["10000", "10100", "10605", "10074.75", "10074.75"]


def lean_case() -> EngineCase:
    """LEAN 2.5.17999: split fill at one timestamp, partial limit, new stop order."""

    t = LEAN_T
    return EngineCase(
        engine="quantconnect_lean",
        engine_version="2.5.17999",
        format_id="backtest-auditor.quantconnect-lean",
        base_currency="USD",
        levels=("order", "fill", "position", "cost", "equity", "return"),
        payloads={
            "lean-orders.csv": CsvPayload(
                "orders",
                (
                    "order_id",
                    "instrument",
                    "created_at",
                    "last_updated_at",
                    "quantity",
                    "side",
                    "type",
                    "time_in_force",
                    "status",
                    "limit_price",
                    "stop_price",
                ),
                (
                    (
                        "1",
                        "SPY",
                        t[0],
                        t[1],
                        "10",
                        "Buy",
                        "Market",
                        "Day",
                        "Filled",
                        "",
                        "",
                    ),
                    (
                        "2",
                        "SPY",
                        t[2],
                        t[3],
                        "4",
                        "Sell",
                        "Limit",
                        "GTC",
                        "PartiallyFilled",
                        "410.25",
                        "",
                    ),
                    (
                        "3",
                        "SPY",
                        t[3],
                        "",
                        "1",
                        "Buy",
                        "StopMarket",
                        "Day",
                        "New",
                        "",
                        "390",
                    ),
                ),
            ),
            "lean-fills.csv": CsvPayload(
                "fills",
                (
                    "fill_id",
                    "order_id",
                    "instrument",
                    "timestamp",
                    "side",
                    "quantity",
                    "price",
                    "currency",
                    "fee_amount",
                    "fee_currency",
                ),
                (
                    ("11", "1", "SPY", t[1], "Buy", "6", "400", "USD", "1", "USD"),
                    ("12", "1", "SPY", t[1], "Buy", "4", "400.5", "USD", "0.5", "EUR"),
                    ("21", "2", "SPY", t[3], "Sell", "2", "410.25", "USD", "0", "USD"),
                ),
            ),
            "portfolio-series.csv": CsvPayload(
                "portfolio",
                ("timestamp", "total_equity"),
                tuple((t[i], LEAN_EQUITY[i]) for i in range(5)),
            ),
        },
    )


# ------------------------- NautilusTrader case ------------------------------

NT_T = [
    "2026-07-01T00:00:00.000000Z",
    "2026-07-01T00:00:01.000001Z",
    "2026-07-02T08:00:00.000000Z",
    "2026-07-02T09:15:00.500000Z",
    "2026-07-03T10:00:00.000000Z",
]


def nautilus_case() -> EngineCase:
    """NautilusTrader 1.231.0: closed long EUR/USD, open short GBP/USD, cash report."""

    t = NT_T
    return EngineCase(
        engine="nautilustrader",
        engine_version="1.231.0",
        format_id="backtest-auditor.nautilustrader",
        base_currency="USD",
        levels=("order", "fill", "trade", "position", "cash", "cost"),
        payloads={
            "nautilustrader-orders.csv": CsvPayload(
                "orders",
                (
                    "order_id",
                    "instrument",
                    "created_at",
                    "last_updated_at",
                    "side",
                    "type",
                    "status",
                    "quantity",
                    "time_in_force",
                    "limit_price",
                    "stop_price",
                ),
                (
                    (
                        "O-1",
                        "EUR/USD.SIM",
                        t[0],
                        t[1],
                        "BUY",
                        "MARKET",
                        "FILLED",
                        "100000",
                        "GTC",
                        "",
                        "",
                    ),
                    (
                        "O-2",
                        "EUR/USD.SIM",
                        t[2],
                        t[3],
                        "SELL",
                        "LIMIT",
                        "FILLED",
                        "100000",
                        "GTC",
                        "1.105",
                        "",
                    ),
                    (
                        "O-3",
                        "GBP/USD.SIM",
                        t[3],
                        t[3],
                        "SELL",
                        "STOP_MARKET",
                        "ACCEPTED",
                        "50000",
                        "DAY",
                        "",
                        "1.25",
                    ),
                    (
                        "O-4",
                        "GBP/USD.SIM",
                        t[4],
                        t[4],
                        "SELL",
                        "MARKET",
                        "FILLED",
                        "50000",
                        "IOC",
                        "",
                        "",
                    ),
                ),
            ),
            "nautilustrader-fills.csv": CsvPayload(
                "fills",
                (
                    "fill_id",
                    "order_id",
                    "instrument",
                    "timestamp",
                    "side",
                    "quantity",
                    "price",
                    "currency",
                    "liquidity_role",
                    "fee_amount",
                    "fee_currency",
                    "position_id",
                ),
                (
                    (
                        "F-1",
                        "O-1",
                        "EUR/USD.SIM",
                        t[1],
                        "BUY",
                        "100000",
                        "1.1",
                        "USD",
                        "TAKER",
                        "2.2",
                        "USD",
                        "P-1",
                    ),
                    (
                        "F-2",
                        "O-2",
                        "EUR/USD.SIM",
                        t[3],
                        "SELL",
                        "100000",
                        "1.105",
                        "USD",
                        "MAKER",
                        "0",
                        "USD",
                        "P-1",
                    ),
                    (
                        "F-3",
                        "O-4",
                        "GBP/USD.SIM",
                        t[4],
                        "SELL",
                        "50000",
                        "1.26",
                        "USD",
                        "TAKER",
                        "1.5",
                        "USD",
                        "P-2",
                    ),
                ),
            ),
            "nautilustrader-positions.csv": CsvPayload(
                "positions",
                (
                    "position_id",
                    "instrument",
                    "opened_at",
                    "last_updated_at",
                    "closed_at",
                    "entry_side",
                    "side",
                    "peak_quantity",
                    "quantity",
                    "entry_price",
                    "exit_price",
                    "realized_pnl",
                    "realized_pnl_currency",
                    "is_snapshot",
                ),
                (
                    (
                        "P-1",
                        "EUR/USD.SIM",
                        t[1],
                        t[3],
                        t[3],
                        "BUY",
                        "FLAT",
                        "100000",
                        "0",
                        "1.1",
                        "1.105",
                        "497.8",
                        "USD",
                        "false",
                    ),
                    (
                        "P-2",
                        "GBP/USD.SIM",
                        t[4],
                        t[4],
                        "",
                        "SELL",
                        "SHORT",
                        "50000",
                        "50000",
                        "1.26",
                        "",
                        "",
                        "USD",
                        "false",
                    ),
                ),
            ),
            "nautilustrader-cash.csv": CsvPayload(
                "cash",
                ("timestamp", "currency", "total"),
                (
                    (t[0], "EUR", "0"),
                    (t[0], "USD", "100000"),
                    (t[1], "USD", "99997.8"),
                    (t[3], "USD", "100497.8"),
                    (t[4], "USD", "100496.3"),
                ),
            ),
        },
    )


ENGINE_CASES: dict[str, Callable[[], EngineCase]] = {
    "vectorbt": vectorbt_case,
    "bt": bt_case,
    "backtrader": backtrader_case,
    "quantconnect_lean": lean_case,
    "nautilustrader": nautilus_case,
}


# ---------------------------------------------------------------------------
# Test 3: each adapter rejects an export with a missing required field.
# ---------------------------------------------------------------------------


def _column_cases() -> list[tuple[str, str, str]]:
    cases = []
    for engine, factory in ENGINE_CASES.items():
        for path, payload in factory().payloads.items():
            for column in payload.headers:
                cases.append((engine, path, column))
    return cases


COLUMN_CASES = _column_cases()


def _column_id(case: tuple[str, str, str]) -> str:
    return f"{case[0]}:{case[1]}:{case[2]}"


def _drop_column(payload: CsvPayload, column: str) -> bytes:
    index = payload.headers.index(column)
    headers = tuple(h for i, h in enumerate(payload.headers) if i != index)
    rows = [
        {h: v for i, (h, v) in enumerate(zip(payload.headers, row)) if i != index}
        for row in payload.rows
    ]
    return _csv_bytes(headers, rows)


def _run_missing_column(
    tmp_path: Path, case: tuple[str, str, str]
) -> EngineAdapterError:
    engine, path, column = case
    engine_case = ENGINE_CASES[engine]()
    data = _drop_column(engine_case.payloads[path], column)
    with pytest.raises(EngineAdapterError) as caught:
        _adapt(tmp_path, engine_case, payload_override={path: data})
    return caught.value


def _names(error: EngineAdapterError, name: str) -> bool:
    if error.field == name:
        return True
    return (
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", error.message)
        is not None
    )


@pytest.mark.parametrize("case", COLUMN_CASES, ids=_column_id)
def test_adapter_rejects_export_missing_required_column_with_typed_error(
    tmp_path: Path, case: tuple[str, str, str]
) -> None:
    """Dropping any contract column fails with a typed, namespaced EngineAdapterError.

    Contract: docs/V1_5D2_CONCRETE_ENGINE_ADAPTERS.md "File contracts"
    (152-155: "CSV columns, order ... are strict"), docs/V1_5D3 "Files and
    deterministic examples" (150-152), docs/V1_5D1 "Fatal failures versus
    warnings" (160-179: ``EngineAdapterError`` with a stable code and a
    namespaced engine detail such as ``vectorbt.missing_column``; context
    includes engine, adapter ID, file).  The envelope is valid so the missing
    column is the only defect.
    """

    engine, path, _column = case
    error = _run_missing_column(tmp_path, case)
    assert error.code is EngineAdapterErrorCode.MAPPING_FAILED, str(error)
    assert error.engine is not None and error.engine.value == engine
    assert error.adapter_id is not None
    assert error.engine_error_code is not None
    assert error.engine_error_code.startswith(f"{engine}."), error.engine_error_code
    assert error.file_path == path, str(error)


def test_adapter_missing_column_error_names_the_missing_column(tmp_path: Path) -> None:
    """The fatal error for a dropped column identifies which column is missing.

    Contract: docs/V1_5D1_SHARED_ADAPTER_FOUNDATION.md:162-164 (error context
    "can include ... file, row, and field") and :176-177 (detail such as
    ``vectorbt.missing_column``); the caller's requirement is "a typed error
    naming the missing field".  Accepted if ``error.field`` equals the column
    or the message mentions it as a whole word.

    One test for finding N14: the first column of each engine's first CSV
    (every engine goes through the shared reader); the parametrized rejection
    test above already drops every column of every file.
    """

    unnamed = []
    for engine in ENGINE_CASES:
        case = next(c for c in COLUMN_CASES if c[0] == engine)
        directory = tmp_path / engine
        directory.mkdir()
        error = _run_missing_column(directory, case)
        if not _names(error, case[2]):
            unnamed.append(f"{_column_id(case)}: {error}")
    assert not unnamed, "missing column not named:\n" + "\n".join(unnamed)


_METADATA_CASES = [
    (engine, key) for engine in ENGINE_CASES for key in METADATA_SCHEMA["required"]
]


def _run_missing_metadata_key(
    tmp_path: Path, engine: str, key: str
) -> EngineAdapterError:
    case = ENGINE_CASES[engine]()
    metadata = {
        "adapter_export_schema_version": "1.0",
        "base_currency": case.base_currency,
    }
    del metadata[key]
    with pytest.raises(EngineAdapterError) as caught:
        _adapt(tmp_path, case, metadata=metadata)
    return caught.value


@pytest.mark.parametrize(("engine", "key"), _METADATA_CASES, ids=lambda v: str(v))
def test_adapter_rejects_metadata_missing_required_key(
    tmp_path: Path, engine: str, key: str
) -> None:
    """adapter-metadata.json without a schema-required key is a typed fatal error.

    Contract: engine-adapter-metadata-1.0.schema.json ``required``
    (adapter_export_schema_version, base_currency); docs/V1_5D2 "File
    contracts" (141-143: metadata contains only those two keys);
    docs/V1_5D1 "Fatal failures versus warnings" (160-179).
    """

    error = _run_missing_metadata_key(tmp_path, engine, key)
    assert error.code is EngineAdapterErrorCode.MAPPING_FAILED, str(error)
    assert error.engine is not None and error.engine.value == engine
    assert error.engine_error_code is not None
    assert error.engine_error_code.startswith(f"{engine}."), error.engine_error_code
    assert error.file_path == "adapter-metadata.json"


def test_adapter_missing_metadata_key_error_names_the_key(tmp_path: Path) -> None:
    """The fatal error for a dropped metadata key identifies which key is missing.

    Contract: docs/V1_5D1_SHARED_ADAPTER_FOUNDATION.md:162-164 (context "can
    include ... field") and the caller's requirement of "a typed error naming
    the missing field" (the envelope reader already does this:
    ``missing=<key>``).

    One test for finding N15, over every engine and every required key.
    """

    unnamed = []
    for engine, key in _METADATA_CASES:
        directory = tmp_path / f"{engine}-{key}"
        directory.mkdir()
        error = _run_missing_metadata_key(directory, engine, key)
        if not _names(error, key):
            unnamed.append(f"{engine}:{key}: {error}")
    assert not unnamed, "missing metadata key not named:\n" + "\n".join(unnamed)


_ENVELOPE_CASES = [
    (engine, (), key) for engine in ENGINE_CASES for key in ENVELOPE_SCHEMA["required"]
] + [
    (engine, ("files", 0), key)
    for engine in ENGINE_CASES
    for key in ENVELOPE_SCHEMA["$defs"]["file"]["required"]
]


@pytest.mark.parametrize(
    ("engine", "path", "key"),
    _ENVELOPE_CASES,
    ids=lambda v: ".".join(map(str, v)) if isinstance(v, tuple) else str(v),
)
def test_adapter_rejects_envelope_missing_required_key(
    tmp_path: Path, engine: str, path: tuple[Any, ...], key: str
) -> None:
    """engine-export.json without a schema-required key fails with INVALID_ENVELOPE naming it.

    Contract: engine-export-envelope-1.0.schema.json ``required`` (root and
    file entries); docs/V1_5D1 "Common engine-export envelope" (56-75:
    "contains exactly ...") and "File safety" (rejects malformed JSON);
    docs/V1_5D1 "Fatal failures versus warnings".
    """

    case = ENGINE_CASES[engine]()

    def mutate(envelope: dict[str, Any]) -> None:
        del _get(envelope, path)[key]

    with pytest.raises(EngineAdapterError) as caught:
        _adapt(tmp_path, case, envelope_mutator=mutate)
    error = caught.value
    assert error.code is EngineAdapterErrorCode.INVALID_ENVELOPE, str(error)
    assert error.file_path == "engine-export.json"
    assert key in error.message, str(error)


# ---------------------------------------------------------------------------
# Test 4: each adapter maps one synthetic engine run correctly.
# ---------------------------------------------------------------------------


def _orders_by_id(artifacts: CanonicalRunArtifacts) -> dict[str, OrderRecord]:
    return {item.order_id: item for item in artifacts.orders}


def _assert_fill_links(artifacts: CanonicalRunArtifacts) -> None:
    orders = _orders_by_id(artifacts)
    for fill in artifacts.fills:
        order = orders[fill.order_id]
        assert (order.instrument_id, order.side) == (fill.instrument_id, fill.side)


def test_vectorbt_adapter_maps_synthetic_run(tmp_path: Path) -> None:
    """vectorbt export -> canonical artifacts carry exactly the synthetic values.

    Contract: docs/V1_5D2_CONCRETE_ENGINE_ADAPTERS.md "vectorbt" (91-105):
    each filled-order row -> one fill + one synthetic FILLED order; positions
    records -> trades (vectorbt grouping); assets/close/value -> position
    snapshots; cash/value -> cash and equity; fees -> fill-linked costs
    (negative = cost, V1_5B artifact table); first return omitted; warnings
    ``vectorbt.filled_orders_reconstructed`` and
    ``vectorbt.initial_return_omitted``; evidence matrix (37-49); D1 "Output
    invariants" (181-197).
    """

    case = vectorbt_case()
    envelope, result = _adapt(tmp_path, case)
    a = result.artifacts
    t = [_ts(x) for x in VBT_T]

    _same_records(
        [
            (
                o.created_at,
                o.instrument_id,
                o.side,
                o.quantity,
                o.status,
                o.submitted_at,
            )
            for o in a.orders
        ],
        [
            (t[0], VBT_I, OrderSide.BUY, D("10"), OrderStatus.FILLED, t[0]),
            (t[3], VBT_I, OrderSide.SELL, D("10"), OrderStatus.FILLED, t[3]),
            (t[4], VBT_I, OrderSide.SELL, D("5"), OrderStatus.FILLED, t[4]),
        ],
    )
    _same_records(
        [
            (f.timestamp, f.instrument_id, f.side, f.quantity, f.price, f.currency)
            for f in a.fills
        ],
        [
            (t[0], VBT_I, OrderSide.BUY, D("10"), D("50.5"), "EUR"),
            (t[3], VBT_I, OrderSide.SELL, D("10"), D("55.25"), "EUR"),
            (t[4], VBT_I, OrderSide.SELL, D("5"), D("54"), "EUR"),
        ],
    )
    _assert_fill_links(a)
    fills_by_id = {f.fill_id: f for f in a.fills}
    _same_records(
        [(c.timestamp, c.cost_type, c.pnl_impact, c.currency) for c in a.costs],
        [
            (t[0], CostType.COMMISSION, D("-0.25"), "EUR"),
            (t[4], CostType.COMMISSION, D("-0.1"), "EUR"),
        ],
    )
    for cost in a.costs:
        fill = fills_by_id[cost.fill_id]
        assert fill.timestamp == cost.timestamp and cost.order_id == fill.order_id
    _same_records(
        [
            (
                tr.opened_at,
                tr.instrument_id,
                tr.direction,
                tr.quantity,
                tr.entry_price,
                tr.currency,
                tr.closed_at,
                tr.exit_price,
                tr.realized_pnl,
            )
            for tr in a.trades
        ],
        [
            (
                t[0],
                VBT_I,
                TradeDirection.LONG,
                D("10"),
                D("50.5"),
                "EUR",
                t[3],
                D("55.25"),
                D("47.25"),
            ),
            (
                t[4],
                VBT_I,
                TradeDirection.SHORT,
                D("5"),
                D("54"),
                "EUR",
                None,
                None,
                None,
            ),
        ],
    )
    _same_records(
        [
            (
                p.timestamp,
                p.instrument_id,
                p.quantity,
                p.currency,
                p.market_price,
                p.market_value,
            )
            for p in a.positions
        ],
        [
            (t[0], VBT_I, D("10"), "EUR", D("51"), D("510")),
            (t[1], VBT_I, D("10"), "EUR", D("52"), D("520")),
            (t[2], VBT_I, D("10"), "EUR", D("53"), D("530")),
            (t[3], VBT_I, D("0"), "EUR", D("55.25"), D("0")),
            (t[4], VBT_I, D("-5"), "EUR", D("54"), D("-270")),
            (t[5], VBT_I, D("-5"), "EUR", D("53"), D("-265")),
        ],
    )
    cash = [
        ("1004.75", "494.75", "510", "510"),
        ("1014.75", "494.75", "520", "520"),
        ("1024.75", "494.75", "530", "530"),
        ("1047.25", "1047.25", "0", "0"),
        ("1047.15", "1317.15", "270", "-270"),
        ("1052.15", "1317.15", "265", "-265"),
    ]
    assert [(b.timestamp, b.currency, b.total) for b in a.cash.balances] == [
        (t[i], "EUR", D(cash[i][1])) for i in range(6)
    ]
    assert all(b.settled in (None, b.total) for b in a.cash.balances)
    assert a.cash.movements is None
    assert [
        (
            e.timestamp,
            e.currency,
            e.total_equity,
            e.cash,
            e.gross_exposure,
            e.net_exposure,
        )
        for e in a.equity
    ] == [
        (t[i], "EUR", D(cash[i][0]), D(cash[i][1]), D(cash[i][2]), D(cash[i][3]))
        for i in range(6)
    ]
    assert [
        (r.start_timestamp, r.end_timestamp, r.value, r.convention) for r in a.returns
    ] == [
        (t[i - 1], t[i], D(VBT_RETURNS[i]), ArtifactReturnConvention.SIMPLE)
        for i in range(1, 6)
    ]
    codes = {w.code for w in result.warnings}
    assert {
        "vectorbt.filled_orders_reconstructed",
        "vectorbt.initial_return_omitted",
    } <= codes
    _assert_common_result(tmp_path, case, envelope, result)


def test_bt_adapter_maps_synthetic_run(tmp_path: Path) -> None:
    """bt export -> fills/synthetic orders, positions, cash, unlinked fee costs, returns.

    Contract: docs/V1_5D2_CONCRETE_ENGINE_ADAPTERS.md "bt" (107-121): each
    transaction -> one fill + one synthetic filled order; position/cash/value
    /fee histories share one index; returns are the exported period changes;
    timestamp-level fees -> commission costs NOT linked to an order or fill;
    warnings ``bt.aggregate_fees_unlinked`` and
    ``bt.transactions_reconstructed_orders``; trade level unavailable
    (matrix 37-49).  A negative bt transaction quantity is a sale.
    """

    case = bt_case()
    envelope, result = _adapt(tmp_path, case)
    a = result.artifacts
    t = [_ts(x) for x in BT_T]
    assert a.trades is None
    _same_records(
        [
            (f.timestamp, f.instrument_id, f.side, f.quantity, f.price, f.currency)
            for f in a.fills
        ],
        [
            (t[1], "AAA", OrderSide.BUY, D("10"), D("100"), "GBP"),
            (t[1], "BBB", OrderSide.BUY, D("5"), D("20"), "GBP"),
            (t[3], "AAA", OrderSide.SELL, D("4"), D("110"), "GBP"),
        ],
    )
    _same_records(
        [
            (o.created_at, o.instrument_id, o.side, o.quantity, o.status)
            for o in a.orders
        ],
        [
            (t[1], "AAA", OrderSide.BUY, D("10"), OrderStatus.FILLED),
            (t[1], "BBB", OrderSide.BUY, D("5"), OrderStatus.FILLED),
            (t[3], "AAA", OrderSide.SELL, D("4"), OrderStatus.FILLED),
        ],
    )
    _assert_fill_links(a)
    _same_records(
        [
            (
                c.timestamp,
                c.cost_type,
                c.pnl_impact,
                c.currency,
                c.order_id,
                c.fill_id,
                c.trade_id,
            )
            for c in a.costs
        ],
        [
            (t[1], CostType.COMMISSION, D("-1.5"), "GBP", None, None, None),
            (t[3], CostType.COMMISSION, D("-0.5"), "GBP", None, None, None),
        ],
    )
    rows = case.payloads["position-snapshots.csv"].rows
    assert [
        (
            p.timestamp,
            p.instrument_id,
            p.quantity,
            p.market_price,
            p.market_value,
            p.currency,
        )
        for p in a.positions
    ] == [
        (_ts(r[0]), r[1], D(r[2]), None if r[3] == "" else D(r[3]), D(r[4]), "GBP")
        for r in rows
    ]
    portfolio = case.payloads["portfolio-series.csv"].rows
    assert [
        (
            e.timestamp,
            e.currency,
            e.total_equity,
            e.cash,
            e.gross_exposure,
            e.net_exposure,
        )
        for e in a.equity
    ] == [(_ts(r[0]), "GBP", D(r[1]), D(r[2]), D(r[3]), D(r[4])) for r in portfolio]
    assert [(b.timestamp, b.currency, b.total) for b in a.cash.balances] == [
        (_ts(r[0]), "GBP", D(r[2])) for r in portfolio
    ]
    assert [
        (r.start_timestamp, r.end_timestamp, r.value, r.convention) for r in a.returns
    ] == [
        (t[i - 1], t[i], D(BT_RETURNS[i - 1]), ArtifactReturnConvention.SIMPLE)
        for i in range(1, 5)
    ]
    codes = {w.code for w in result.warnings}
    assert {
        "bt.aggregate_fees_unlinked",
        "bt.transactions_reconstructed_orders",
    } <= codes
    _assert_common_result(tmp_path, case, envelope, result)


def test_backtrader_adapter_maps_synthetic_run(tmp_path: Path) -> None:
    """Backtrader export -> exact order lifecycle, fills, linked commission, derived returns.

    Contract: docs/V1_5D2_CONCRETE_ENGINE_ADAPTERS.md "Backtrader" (123-137):
    final order lifecycle fields, one fill per execution bit, per-bar positions
    at close, broker cash/value series, execution-bit commission -> fill-linked
    cost, simple returns derived from consecutive broker equity; known order
    types/statuses produce no custom/margin warnings; matrix (37-49).
    Expected returns are computed here with exact rational arithmetic.
    """

    case = backtrader_case()
    envelope, result = _adapt(tmp_path, case)
    a = result.artifacts
    t = [_ts(x) for x in BTR_T]
    orders = sorted(a.orders, key=lambda o: o.created_at)
    assert [
        (
            o.created_at,
            o.submitted_at,
            o.last_updated_at,
            o.instrument_id,
            o.side,
            o.quantity,
            o.order_type,
            o.status,
            o.expires_at,
            o.limit_price,
            o.stop_price,
        )
        for o in orders
    ] == [
        (
            t[0],
            t[1],
            t[1],
            "XYZ",
            OrderSide.BUY,
            D("10"),
            OrderType.MARKET,
            OrderStatus.FILLED,
            None,
            None,
            None,
        ),
        (
            t[2],
            t[2],
            t[3],
            "XYZ",
            OrderSide.SELL,
            D("4"),
            OrderType.LIMIT,
            OrderStatus.PARTIALLY_FILLED,
            t[5],
            D("120.5"),
            None,
        ),
        (
            t[3],
            t[3],
            t[3],
            "XYZ",
            OrderSide.SELL,
            D("1"),
            OrderType.STOP,
            OrderStatus.CANCELED,
            None,
            None,
            D("90"),
        ),
    ]
    assert orders[1].time_in_force is TimeInForce.GTD
    assert orders[2].parent_order_id == orders[0].order_id
    assert orders[0].parent_order_id is None and orders[1].parent_order_id is None
    assert [
        (f.timestamp, f.side, f.quantity, f.price, f.currency) for f in a.fills
    ] == [
        (t[1], OrderSide.BUY, D("10"), D("101"), "USD"),
        (t[3], OrderSide.SELL, D("2"), D("120.5"), "USD"),
    ]
    assert (
        a.fills[0].order_id == orders[0].order_id
        and a.fills[1].order_id == orders[1].order_id
    )
    assert [
        (c.timestamp, c.cost_type, c.pnl_impact, c.currency, c.order_id, c.fill_id)
        for c in a.costs
    ] == [
        (
            t[1],
            CostType.COMMISSION,
            D("-1.01"),
            "USD",
            orders[0].order_id,
            a.fills[0].fill_id,
        )
    ]
    pos_rows = case.payloads["position-snapshots.csv"].rows
    assert [
        (
            p.timestamp,
            p.instrument_id,
            p.quantity,
            p.market_price,
            p.market_value,
            p.currency,
        )
        for p in a.positions
    ] == [(_ts(r[0]), r[1], D(r[2]), D(r[3]), D(r[4]), "USD") for r in pos_rows]
    portfolio = case.payloads["portfolio-series.csv"].rows
    assert [
        (
            e.timestamp,
            e.total_equity,
            e.cash,
            e.gross_exposure,
            e.net_exposure,
            e.currency,
        )
        for e in a.equity
    ] == [(_ts(r[0]), D(r[1]), D(r[2]), D(r[3]), D(r[4]), "USD") for r in portfolio]
    expected_returns = [
        Fraction(BTR_EQUITY[i]) / Fraction(BTR_EQUITY[i - 1]) - 1 for i in range(1, 6)
    ]
    assert expected_returns == [
        Fraction(1, 100),
        Fraction(5, 100),
        Fraction(-5, 100),
        0,
        Fraction(1, 10),
    ]
    assert [
        (r.start_timestamp, r.end_timestamp, Fraction(r.value), r.convention)
        for r in a.returns
    ] == [
        (t[i - 1], t[i], expected_returns[i - 1], ArtifactReturnConvention.SIMPLE)
        for i in range(1, 6)
    ]
    assert result.warnings == ()
    _assert_common_result(tmp_path, case, envelope, result)


def test_quantconnect_lean_adapter_maps_synthetic_run(tmp_path: Path) -> None:
    """LEAN export -> orders, per-event fills, fee-currency costs, net positions, returns.

    Contract: docs/V1_5D3_LEAN_NAUTILUS_AND_HARDENING.md "QuantConnect LEAN
    workflow and semantics" (81-95): creation time used as submission time
    for submitted states (with warning); each non-zero fill -> one fill whose
    fee becomes a fill-linked commission "in the fee's disclosed currency";
    net quantity snapshots accumulated by (timestamp, instrument) with no
    invented valuation; Strategy Equity -> total equity; consecutive values ->
    simple returns; producer-declared version warning (25-28); matrix (39-51).
    """

    case = lean_case()
    envelope, result = _adapt(tmp_path, case)
    a = result.artifacts
    t = [_ts(x) for x in LEAN_T]
    orders = sorted(a.orders, key=lambda o: o.created_at)
    assert [
        (
            o.created_at,
            o.submitted_at,
            o.last_updated_at,
            o.side,
            o.quantity,
            o.order_type,
            o.time_in_force,
            o.status,
            o.limit_price,
            o.stop_price,
        )
        for o in orders
    ] == [
        (
            t[0],
            t[0],
            t[1],
            OrderSide.BUY,
            D("10"),
            OrderType.MARKET,
            TimeInForce.DAY,
            OrderStatus.FILLED,
            None,
            None,
        ),
        (
            t[2],
            t[2],
            t[3],
            OrderSide.SELL,
            D("4"),
            OrderType.LIMIT,
            TimeInForce.GTC,
            OrderStatus.PARTIALLY_FILLED,
            D("410.25"),
            None,
        ),
        (
            t[3],
            None,
            t[3],
            OrderSide.BUY,
            D("1"),
            OrderType.STOP,
            TimeInForce.DAY,
            OrderStatus.CREATED,
            None,
            D("390"),
        ),
    ]
    _same_records(
        [
            (f.timestamp, f.instrument_id, f.side, f.quantity, f.price, f.currency)
            for f in a.fills
        ],
        [
            (t[1], "SPY", OrderSide.BUY, D("6"), D("400"), "USD"),
            (t[1], "SPY", OrderSide.BUY, D("4"), D("400.5"), "USD"),
            (t[3], "SPY", OrderSide.SELL, D("2"), D("410.25"), "USD"),
        ],
    )
    _assert_fill_links(a)
    fills_by_id = {f.fill_id: f for f in a.fills}
    _same_records(
        [
            (
                c.timestamp,
                c.cost_type,
                c.pnl_impact,
                c.currency,
                fills_by_id[c.fill_id].quantity,
            )
            for c in a.costs
        ],
        [
            (t[1], CostType.COMMISSION, D("-1"), "USD", D("6")),
            (t[1], CostType.COMMISSION, D("-0.5"), "EUR", D("4")),
        ],
    )
    assert [
        (
            p.timestamp,
            p.instrument_id,
            p.quantity,
            p.currency,
            p.market_price,
            p.market_value,
            p.average_cost,
            p.realized_pnl,
            p.unrealized_pnl,
        )
        for p in a.positions
    ] == [
        (t[1], "SPY", D("10"), "USD", None, None, None, None, None),
        (t[3], "SPY", D("8"), "USD", None, None, None, None, None),
    ]
    portfolio = case.payloads["portfolio-series.csv"].rows
    assert [(e.timestamp, e.total_equity, e.currency, e.cash) for e in a.equity] == [
        (_ts(r[0]), D(r[1]), "USD", None) for r in portfolio
    ]
    values = [Fraction(r[1]) for r in portfolio]
    expected = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]
    assert [
        (r.start_timestamp, r.end_timestamp, Fraction(r.value), r.convention)
        for r in a.returns
    ] == [
        (
            _ts(portfolio[i - 1][0]),
            _ts(portfolio[i][0]),
            expected[i - 1],
            ArtifactReturnConvention.SIMPLE,
        )
        for i in range(1, len(portfolio))
    ]
    assert a.cash is None and a.trades is None
    codes = {w.code for w in result.warnings}
    assert "quantconnect_lean.engine_version_producer_declared" in codes
    assert any("submission" in code or "submitted" in code for code in codes), codes
    _assert_common_result(tmp_path, case, envelope, result)


def test_nautilustrader_adapter_maps_synthetic_run(tmp_path: Path) -> None:
    """NautilusTrader export -> orders, fills with liquidity/fees, position_id trades, cash.

    Contract: docs/V1_5D3_LEAN_NAUTILUS_AND_HARDENING.md "NautilusTrader
    workflow and semantics" (128-140): final lifecycle/type/TIF/price fields;
    one fill per OrderFilled with linked commission and liquidity side;
    positions -> trades via native ``position_id`` grouping without fabricated
    fill links; quantity-only snapshots summed by instrument at each update
    timestamp; account report -> timestamp/currency cash totals; matrix
    (39-51: no equity/return).
    """

    case = nautilus_case()
    envelope, result = _adapt(tmp_path, case)
    a = result.artifacts
    t = [_ts(x) for x in NT_T]
    orders = sorted(a.orders, key=lambda o: o.created_at)
    assert [
        (
            o.created_at,
            o.last_updated_at,
            o.instrument_id,
            o.side,
            o.quantity,
            o.order_type,
            o.time_in_force,
            o.status,
            o.limit_price,
            o.stop_price,
        )
        for o in orders
    ] == [
        (
            t[0],
            t[1],
            "EUR/USD.SIM",
            OrderSide.BUY,
            D("100000"),
            OrderType.MARKET,
            TimeInForce.GTC,
            OrderStatus.FILLED,
            None,
            None,
        ),
        (
            t[2],
            t[3],
            "EUR/USD.SIM",
            OrderSide.SELL,
            D("100000"),
            OrderType.LIMIT,
            TimeInForce.GTC,
            OrderStatus.FILLED,
            D("1.105"),
            None,
        ),
        (
            t[3],
            t[3],
            "GBP/USD.SIM",
            OrderSide.SELL,
            D("50000"),
            OrderType.STOP,
            TimeInForce.DAY,
            OrderStatus.ACCEPTED,
            None,
            D("1.25"),
        ),
        (
            t[4],
            t[4],
            "GBP/USD.SIM",
            OrderSide.SELL,
            D("50000"),
            OrderType.MARKET,
            TimeInForce.IOC,
            OrderStatus.FILLED,
            None,
            None,
        ),
    ]
    assert [
        (
            f.timestamp,
            f.instrument_id,
            f.side,
            f.quantity,
            f.price,
            f.currency,
            f.liquidity_role,
        )
        for f in a.fills
    ] == [
        (
            t[1],
            "EUR/USD.SIM",
            OrderSide.BUY,
            D("100000"),
            D("1.1"),
            "USD",
            LiquidityRole.TAKER,
        ),
        (
            t[3],
            "EUR/USD.SIM",
            OrderSide.SELL,
            D("100000"),
            D("1.105"),
            "USD",
            LiquidityRole.MAKER,
        ),
        (
            t[4],
            "GBP/USD.SIM",
            OrderSide.SELL,
            D("50000"),
            D("1.26"),
            "USD",
            LiquidityRole.TAKER,
        ),
    ]
    _assert_fill_links(a)
    fills_by_id = {f.fill_id: f for f in a.fills}
    assert [
        (
            c.timestamp,
            c.cost_type,
            c.pnl_impact,
            c.currency,
            fills_by_id[c.fill_id].price,
        )
        for c in a.costs
    ] == [
        (t[1], CostType.COMMISSION, D("-2.2"), "USD", D("1.1")),
        (t[4], CostType.COMMISSION, D("-1.5"), "USD", D("1.26")),
    ]
    assert [
        (
            tr.opened_at,
            tr.instrument_id,
            tr.direction,
            tr.quantity,
            tr.entry_price,
            tr.currency,
            tr.closed_at,
            tr.exit_price,
            tr.realized_pnl,
            tr.fill_ids,
        )
        for tr in a.trades
    ] == [
        (
            t[1],
            "EUR/USD.SIM",
            TradeDirection.LONG,
            D("100000"),
            D("1.1"),
            "USD",
            t[3],
            D("1.105"),
            D("497.8"),
            (),
        ),
        (
            t[4],
            "GBP/USD.SIM",
            TradeDirection.SHORT,
            D("50000"),
            D("1.26"),
            "USD",
            None,
            None,
            None,
            (),
        ),
    ]
    assert all("position_id" in tr.grouping_method for tr in a.trades)
    assert [
        (
            p.timestamp,
            p.instrument_id,
            p.quantity,
            p.currency,
            p.market_price,
            p.market_value,
        )
        for p in a.positions
    ] == [
        (t[3], "EUR/USD.SIM", D("0"), "USD", None, None),
        (t[4], "GBP/USD.SIM", D("-50000"), "USD", None, None),
    ]
    assert [(b.timestamp, b.currency, b.total, b.settled) for b in a.cash.balances] == [
        (t[0], "EUR", D("0"), None),
        (t[0], "USD", D("100000"), None),
        (t[1], "USD", D("99997.8"), None),
        (t[3], "USD", D("100497.8"), None),
        (t[4], "USD", D("100496.3"), None),
    ]
    assert a.equity is None and a.returns is None
    _assert_common_result(tmp_path, case, envelope, result)


def test_vectorbt_adapter_does_not_silently_round_high_precision_values(
    tmp_path: Path,
) -> None:
    """A canonical 30-significant-digit export value is mapped exactly or rejected.

    Contract: docs/V1_5D2 "File contracts" (152-155: decimal spelling is
    strict and values "fail instead of being repaired"), docs/V1_5B "Numeric
    and time rules" (Decimal prevents representation drift) and ADR-003
    ("Exact Decimal ... semantics survive file exchange").  Shows that the
    domain-level rounding (see the bundle precision test) changes a number
    that an adapter emits into the canonical evidence.
    """

    case = vectorbt_case()
    rows = list(case.payloads["portfolio-series.csv"].rows)
    precise = "123456789012.123456789012345678"
    rows[0] = (rows[0][0], rows[0][1], precise, *rows[0][3:])
    payloads = dict(case.payloads)
    payloads["portfolio-series.csv"] = dataclasses.replace(
        case.payloads["portfolio-series.csv"], rows=tuple(rows)
    )
    case = dataclasses.replace(case, payloads=payloads)
    try:
        _envelope, result = _adapt(tmp_path, case)
    except EngineAdapterError:
        return  # explicit typed rejection satisfies the contract
    assert result.artifacts.cash.balances[0].total == Decimal(precise), (
        f"mapped {result.artifacts.cash.balances[0].total!r}, exported {precise}"
    )
