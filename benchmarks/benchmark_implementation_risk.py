"""Reproducible, budgeted benchmark for the complete V1.5 pipeline."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median

from backtest_auditor.implementation_risk import (
    ArtifactReturnConvention,
    CanonicalArtifactFileBundleAdapter,
    CanonicalRunArtifacts,
    CostRecord,
    CostType,
    EquityPoint,
    ImplementationRiskAuditService,
    OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
    ReturnPoint,
    TimeInForce,
)
from scripts.generate_v1_5i_report_example import _bundle, build_policies


def build_synthetic_reconciliation(
    *, record_count: int
) -> tuple[CanonicalRunArtifacts, CanonicalRunArtifacts]:
    """Build aligned reference/candidate evidence without file-I/O timing noise."""

    if record_count <= 0:
        raise ValueError("record_count must be positive.")
    reference_base = _bundle(candidate=False)
    candidate_base = _bundle(candidate=True)
    start = datetime(2020, 1, 1, 14, 30, tzinfo=timezone.utc)
    reference_orders = []
    candidate_orders = []
    reference_costs = []
    candidate_costs = []
    reference_equity = []
    candidate_equity = []
    reference_returns = []
    candidate_returns = []
    for index in range(record_count):
        end = start + timedelta(days=index + 1)
        reference_orders.append(
            OrderRecord(
                f"order-a-{index:06d}",
                end,
                "AAPL",
                OrderSide.BUY,
                Decimal(10),
                OrderType.MARKET,
                TimeInForce.DAY,
                OrderStatus.SUBMITTED,
                submitted_at=end,
            )
        )
        candidate_orders.append(
            replace(
                reference_orders[-1],
                order_id=f"order-b-{index:06d}",
                quantity=Decimal(12),
            )
        )
        reference_costs.append(
            CostRecord(
                f"cost-a-{index:06d}",
                end,
                CostType.COMMISSION,
                Decimal("-1"),
                "USD",
            )
        )
        candidate_costs.append(
            replace(
                reference_costs[-1],
                cost_id=f"cost-b-{index:06d}",
                pnl_impact=Decimal("-1.25"),
            )
        )
        reference_equity.append(EquityPoint(end, "USD", Decimal("100000")))
        candidate_equity.append(EquityPoint(end, "USD", Decimal("99997.5")))
        reference_returns.append(
            ReturnPoint(
                end - timedelta(days=1),
                end,
                Decimal("0.01"),
                ArtifactReturnConvention.SIMPLE,
            )
        )
        candidate_returns.append(
            ReturnPoint(
                end - timedelta(days=1),
                end,
                Decimal("0.009975"),
                ArtifactReturnConvention.SIMPLE,
            )
        )
    return (
        replace(
            reference_base,
            orders=tuple(reference_orders),
            costs=tuple(reference_costs),
            equity=tuple(reference_equity),
            returns=tuple(reference_returns),
        ),
        replace(
            candidate_base,
            orders=tuple(candidate_orders),
            costs=tuple(candidate_costs),
            equity=tuple(candidate_equity),
            returns=tuple(candidate_returns),
        ),
    )


def benchmark_implementation_risk(
    *,
    record_count: int,
    repeats: int,
    time_budget_seconds: float,
    memory_budget_mib: float,
) -> dict[str, object]:
    if repeats <= 0:
        raise ValueError("repeats must be positive.")
    if time_budget_seconds <= 0 or memory_budget_mib <= 0:
        raise ValueError("performance budgets must be positive.")
    reference, candidate = build_synthetic_reconciliation(record_count=record_count)
    policies = build_policies(reference, candidate)
    service = ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter())
    durations = []
    result = None
    tracemalloc.start()
    try:
        for _ in range(repeats):
            started = time.perf_counter()
            result = service.audit((reference, candidate), *policies)
            durations.append(time.perf_counter() - started)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result is not None
    median_seconds = median(durations)
    peak_mib = peak_bytes / (1024 * 1024)
    budget_met = median_seconds <= time_budget_seconds and peak_mib <= memory_budget_mib
    return {
        "budget_met": budget_met,
        "candidate_count": len(result.assessment.candidates),
        "finding_count": len(result.findings),
        "median_seconds": median_seconds,
        "memory_budget_mib": memory_budget_mib,
        "peak_mib": peak_mib,
        "record_count_per_level": record_count,
        "repeats": repeats,
        "time_budget_seconds": time_budget_seconds,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=2_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--time-budget-seconds", type=float, default=10.0)
    parser.add_argument("--memory-budget-mib", type=float, default=512.0)
    arguments = parser.parse_args(argv)
    try:
        result = benchmark_implementation_risk(
            record_count=arguments.records,
            repeats=arguments.repeats,
            time_budget_seconds=arguments.time_budget_seconds,
            memory_budget_mib=arguments.memory_budget_mib,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["budget_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
