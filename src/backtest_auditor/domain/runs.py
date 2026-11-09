from dataclasses import dataclass

from backtest_auditor.domain.metadata import (
    ObservationCalendarSpec,
    ReturnConstructionSpec,
)
from backtest_auditor.domain.series import RegimeSeries, ReturnSeries


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    benchmark_id: str
    returns: ReturnSeries
    observation_calendar: ObservationCalendarSpec | None = None
    return_construction: ReturnConstructionSpec | None = None

    def __post_init__(self) -> None:
        if not self.benchmark_id.strip():
            raise ValueError("benchmark_id must not be empty.")


@dataclass(frozen=True, slots=True)
class StrategyRun:
    run_id: str
    returns: ReturnSeries
    observation_calendar: ObservationCalendarSpec | None = None
    return_construction: ReturnConstructionSpec | None = None
    benchmark: BenchmarkRun | None = None
    risk_free_returns: ReturnSeries | None = None
    gross_returns: ReturnSeries | None = None
    regimes: RegimeSeries | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty.")
