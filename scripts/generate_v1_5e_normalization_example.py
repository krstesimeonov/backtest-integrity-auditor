"""Generate or verify the executable V1.5E normalization example."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from backtest_auditor.implementation_risk import (
    ArtifactReturnConvention,
    AssetClass,
    CanonicalArtifactFileBundleAdapter,
    CanonicalFrequency,
    CanonicalRunArtifacts,
    CanonicalRunSpecification,
    ComparisonLevel,
    CurrencyNormalizationRule,
    EngineRunReference,
    EquityPoint,
    FrequencyKind,
    FrequencyNormalizationRule,
    InstrumentIdentityRule,
    InstrumentReference,
    MarketDataObservation,
    ModelSpecification,
    ReconciliationNormalizationPlan,
    ReconciliationNormalizationService,
    ReconciliationScope,
    ReturnPoint,
    RunNormalizationPolicy,
    SimulationSpecification,
    StrategyIdentityRule,
    StrategySpecification,
    TimestampNormalizationRule,
    normalization_plan_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = ROOT / "examples" / "v1_5e_normalization"


def _bundle(
    run: EngineRunReference,
    *,
    strategy_id: str,
    instrument_id: str,
    symbol: str,
    currency: str,
    frequency: str,
    offset_seconds: int,
) -> CanonicalRunArtifacts:
    start = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc) + timedelta(
        seconds=offset_seconds
    )
    end = start + timedelta(minutes=1)
    instrument = InstrumentReference(
        instrument_id,
        AssetClass.EQUITY,
        symbol,
        currency,
        "XNAS",
    )
    specification = CanonicalRunSpecification(
        StrategySpecification(
            strategy_id,
            "One-minute momentum",
            "d" * 64,
            (instrument,),
            (),
            frequency,
            "after bar availability",
            ModelSpecification("momentum"),
            ModelSpecification("fixed quantity"),
            "1",
        ),
        SimulationSpecification(
            currency,
            Decimal("100000"),
            "XNYS",
            "America/New_York",
            "split adjusted",
            "next bar",
            ModelSpecification("next bar"),
            ModelSpecification("average cost"),
            (),
            False,
            False,
        ),
    )
    return CanonicalRunArtifacts(
        run,
        specification=specification,
        market_data=(
            MarketDataObservation(
                f"{run.run_id}-close",
                instrument_id,
                start,
                "close",
                Decimal("100.25"),
                start,
                "price",
            ),
        ),
        equity=(EquityPoint(end, currency, Decimal("100500")),),
        returns=(
            ReturnPoint(
                start,
                end,
                Decimal("0.005"),
                ArtifactReturnConvention.SIMPLE,
            ),
        ),
    )


def build_example() -> tuple[
    ReconciliationScope,
    tuple[CanonicalRunArtifacts, CanonicalRunArtifacts],
    ReconciliationNormalizationPlan,
]:
    reference_run = EngineRunReference("engine-a-run", "Engine A", "1.0", "a" * 64)
    candidate_run = EngineRunReference("engine-b-run", "Engine B", "2.0", "b" * 64)
    reference = _bundle(
        reference_run,
        strategy_id="engine-a:momentum",
        instrument_id="AAPL.XNAS",
        symbol="AAPL",
        currency="USD",
        frequency="one minute",
        offset_seconds=0,
    )
    candidate = _bundle(
        candidate_run,
        strategy_id="engine-b/momentum",
        instrument_id="XNAS:AAPL",
        symbol="AAPL.XNAS",
        currency="USX",
        frequency="1-MINUTE",
        offset_seconds=30,
    )
    scope = ReconciliationScope(
        "v1-5e-example",
        reference_run,
        (candidate_run,),
        (
            ComparisonLevel.STRATEGY_SPECIFICATION,
            ComparisonLevel.MARKET_DATA,
            ComparisonLevel.EQUITY,
            ComparisonLevel.RETURN,
        ),
    )
    target = InstrumentReference(
        "AAPL.CANONICAL",
        AssetClass.EQUITY,
        "AAPL",
        "USD",
        "XNAS",
    )
    canonical_frequency = CanonicalFrequency("PT1M", FrequencyKind.FIXED, 60_000_000)

    def policy(
        bundle: CanonicalRunArtifacts,
        *,
        source_strategy: str,
        source_instrument: str,
        source_currency: str,
        source_frequency: str,
        offset_microseconds: int | None,
    ) -> RunNormalizationPolicy:
        timestamps = (
            ()
            if offset_microseconds is None
            else tuple(
                TimestampNormalizationRule(
                    level,
                    offset_microseconds,
                    "producer clock comparison against the same UTC event",
                )
                for level in (
                    ComparisonLevel.MARKET_DATA,
                    ComparisonLevel.EQUITY,
                    ComparisonLevel.RETURN,
                )
            )
        )
        return RunNormalizationPolicy(
            bundle.run,
            StrategyIdentityRule(
                source_strategy,
                "momentum-canonical",
                "identical reviewed strategy source",
            ),
            (
                InstrumentIdentityRule(
                    source_instrument,
                    target,
                    "venue and vendor instrument cross-reference",
                ),
            ),
            (
                CurrencyNormalizationRule(
                    source_currency,
                    "USD",
                    "denomination identifier cross-reference; no FX conversion",
                ),
            ),
            timestamps,
            FrequencyNormalizationRule(
                canonical_frequency,
                "explicit one-minute source contracts",
                source_frequency,
            ),
        )

    plan = ReconciliationNormalizationPlan(
        scope.reconciliation_id,
        (
            policy(
                reference,
                source_strategy="engine-a:momentum",
                source_instrument="AAPL.XNAS",
                source_currency="USD",
                source_frequency="one minute",
                offset_microseconds=None,
            ),
            policy(
                candidate,
                source_strategy="engine-b/momentum",
                source_instrument="XNAS:AAPL",
                source_currency="USX",
                source_frequency="1-MINUTE",
                offset_microseconds=-30_000_000,
            ),
        ),
    )
    return scope, (reference, candidate), plan


def generate_example(destination: Path) -> None:
    scope, bundles, plan = build_example()
    result = ReconciliationNormalizationService(
        CanonicalArtifactFileBundleAdapter()
    ).normalize(scope, bundles, plan)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "normalization-plan.json").write_text(
        normalization_plan_to_json(plan) + "\n",
        encoding="utf-8",
    )
    summary = {
        "reconciliation_id": result.scope.reconciliation_id,
        "plan_sha256": result.plan_sha256,
        "runs": [
            {
                "run_id": run.source_run.run_id,
                "canonical_bundle_sha256": run.canonical_bundle_sha256,
                "canonical_frequency": (
                    None
                    if run.canonical_frequency is None
                    else run.canonical_frequency.frequency_id
                ),
                "normalized_total_equity": format(
                    run.artifacts.equity[0].total_equity,
                    "f",  # type: ignore[index]
                ),
                "changes": [
                    {
                        "dimension": change.dimension.value,
                        "level": None if change.level is None else change.level.value,
                        "source_value": change.source_value,
                        "normalized_value": change.normalized_value,
                        "rationale": change.rationale,
                    }
                    for change in run.changes
                ],
            }
            for run in result.runs
        ],
    }
    (destination / "normalized-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _tree(directory: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(directory): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if not arguments.check:
        generate_example(EXAMPLE_ROOT)
        return 0
    if not EXAMPLE_ROOT.is_dir():
        raise SystemExit(f"missing example directory: {EXAMPLE_ROOT}")
    with tempfile.TemporaryDirectory() as raw_temporary:
        generated = Path(raw_temporary) / "example"
        generate_example(generated)
        if _tree(generated) != _tree(EXAMPLE_ROOT):
            raise SystemExit("V1.5E example differs from deterministic generator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
