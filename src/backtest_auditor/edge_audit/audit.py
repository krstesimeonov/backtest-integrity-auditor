"""Run every V4 method on one trade log and collect the results.

Randomness: every analysis draws from its own child of
``numpy.random.SeedSequence(settings.seed)``, so changing the number of draws
in one analysis never changes another's numbers, and the same input with the
same settings gives byte-identical reports.

The verdict (``luck_vs_skill.verdict``) uses no random numbers at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from backtest_auditor.domain.assumptions import SerialDependenceSpec
from backtest_auditor.edge_audit.conditional import (
    TercileSplit,
    split_by_terciles,
    trailing_volatility,
)
from backtest_auditor.edge_audit.costs import CostSensitivity, analyse_costs
from backtest_auditor.edge_audit.decay import (
    DEFAULT_HORIZON,
    DecayResult,
    analyse_decay,
)
from backtest_auditor.edge_audit.decay_thresholds import ALPHAS as DECAY_ALPHAS
from backtest_auditor.edge_audit.decay_thresholds import HORIZONS as DECAY_HORIZONS
from backtest_auditor.edge_audit.metrics import (
    Interval,
    bootstrap_distributions,
    expectancy,
    percentile_interval,
    profit_factor,
    win_rate,
)
from backtest_auditor.edge_audit.schema import PriceTable, TradeLog
from backtest_auditor.edge_audit.sizing import SizingResult, analyse_sizing
from backtest_auditor.edge_audit.skill import (
    LuckVsSkill,
    assess_luck_vs_skill,
    trade_clock_series,
)
from backtest_auditor.edge_audit.timing import (
    TIMING_MODES,
    TimingResult,
    analyse_timing,
)
from backtest_auditor.statistics.serial_dependence import calculate_serial_dependence

DEFAULT_SEED = 20261103
DECAY_ALPHA_RANGE = (DECAY_ALPHAS[0], DECAY_ALPHAS[-1])
DECAY_HORIZON_RANGE = (DECAY_HORIZONS[0], DECAY_HORIZONS[-1])


@dataclass(frozen=True, slots=True)
class AuditSettings:
    """Every choice that can change a number in the report."""

    declared_trials: int
    confidence_level: float = 0.95
    bootstrap_replications: int = 2000
    mean_block_length: int = 1
    seed: int = DEFAULT_SEED
    trial_sharpe_std: float | None = None
    timing_mode: str = "day"
    day_timezone: str = "UTC"
    timing_draws: int = 2000
    permutation_draws: int = 2000
    volatility_lookback_bars: int = 50
    cost_grid_bps: tuple[float, ...] = (0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)
    reference_trades: int | None = None
    decay_shift_sigma: float | None = None
    decay_false_alarm_probability: float = 0.05
    decay_horizon: int = DEFAULT_HORIZON
    rolling_window: int | None = None

    def __post_init__(self) -> None:
        def positive_int(name: str, minimum: int = 1) -> None:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}.")

        positive_int("declared_trials")
        positive_int("bootstrap_replications", 2)
        positive_int("mean_block_length")
        positive_int("seed", 0)
        positive_int("timing_draws", 1)
        positive_int("permutation_draws", 1)
        positive_int("volatility_lookback_bars", 2)
        positive_int("decay_horizon", DECAY_HORIZON_RANGE[0])
        if self.decay_horizon > DECAY_HORIZON_RANGE[1]:
            raise ValueError(
                f"decay_horizon must be at most {DECAY_HORIZON_RANGE[1]:,} trades "
                "(the end of the calibration table)."
            )
        for name in ("reference_trades", "rolling_window"):
            if getattr(self, name) is not None:
                positive_int(name, 2)
        for name in ("confidence_level",):
            value = getattr(self, name)
            if not (math.isfinite(value) and 0.5 < value < 1.0):
                raise ValueError(f"{name} must be strictly between 0.5 and 1.0.")
        low, high = DECAY_ALPHA_RANGE
        value = self.decay_false_alarm_probability
        if not (math.isfinite(value) and low <= value <= high):
            raise ValueError(
                f"decay_false_alarm_probability must be between {low} and {high} "
                "(the range of the calibration table)."
            )
        if self.trial_sharpe_std is not None and not (
            math.isfinite(self.trial_sharpe_std) and self.trial_sharpe_std >= 0.0
        ):
            raise ValueError("trial_sharpe_std must be finite and >= 0.")
        if self.decay_shift_sigma is not None and not (
            math.isfinite(self.decay_shift_sigma) and self.decay_shift_sigma > 0.0
        ):
            raise ValueError("decay_shift_sigma must be finite and > 0.")
        if self.timing_mode not in TIMING_MODES:
            raise ValueError(f"timing_mode must be one of {TIMING_MODES}.")
        try:
            ZoneInfo(self.day_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("day_timezone must be an IANA timezone name.") from error
        if not self.cost_grid_bps or not all(
            math.isfinite(value) for value in self.cost_grid_bps
        ):
            raise ValueError("cost_grid_bps must hold finite numbers.")


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    trade_count: int
    winning_trades: int
    losing_trades: int
    flat_trades: int
    total_net_pnl: float
    total_gross_pnl: float
    total_fees: float
    expectancy: Interval
    profit_factor: Interval
    win_rate: Interval
    average_win: float | None
    average_loss: float | None
    payoff_ratio: float | None
    mean_net_return_bps: float
    median_holding_hours: float
    first_entry: str
    last_exit: str
    span_years: float
    instruments: tuple[str, ...]
    currency: str | None
    max_concurrent_trades: int
    serial_dependence_p_value: float | None
    lag_one_autocorrelation: float | None


@dataclass(frozen=True, slots=True)
class EdgeAuditResult:
    settings: AuditSettings
    performance: PerformanceSummary
    luck_vs_skill: LuckVsSkill
    timing: TimingResult
    holding_period: TercileSplit
    volatility_regime: TercileSplit
    costs: CostSensitivity
    decay: DecayResult
    sizing: SizingResult
    warnings: tuple[str, ...] = field(default_factory=tuple)


def run_edge_audit(
    trades: TradeLog,
    prices: PriceTable | None,
    settings: AuditSettings,
) -> EdgeAuditResult:
    """The whole audit; the CLI and the tests call this one function."""

    net = trades.net_pnl
    gross = trades.gross_pnl
    notional = trades.notional
    net_return = trades.net_return
    count = len(trades)
    span_years = trades.span_years
    seeds = np.random.SeedSequence(settings.seed).spawn(8)

    def child_seed(index: int) -> int:
        return int(seeds[index].generate_state(1)[0])

    luck = assess_luck_vs_skill(
        net,
        span_years=span_years,
        declared_trials=settings.declared_trials,
        confidence_level=settings.confidence_level,
        trial_sharpe_std=settings.trial_sharpe_std,
    )

    shared = bootstrap_distributions(
        count,
        {
            "expectancy": lambda idx: float(np.mean(net[idx])),
            "profit_factor": lambda idx: profit_factor(net[idx]),
            "win_rate": lambda idx: win_rate(net[idx]),
            "notional": lambda idx: float(np.mean(notional[idx])),
            "fixed_size": lambda idx: float(
                np.mean(net_return[idx]) * np.mean(notional[idx])
            ),
            "sizing": lambda idx: float(
                np.mean(net[idx]) - np.mean(net_return[idx]) * np.mean(notional[idx])
            ),
        },
        replications=settings.bootstrap_replications,
        mean_block_length=settings.mean_block_length,
        seed=child_seed(0),
    )
    confidence = settings.confidence_level
    expectancy_interval = percentile_interval(
        expectancy(net), shared["expectancy"], confidence_level=confidence
    )
    performance = _performance(
        trades, settings, expectancy_interval, shared, span_years
    )

    timing = analyse_timing(
        trades,
        prices,
        mode=settings.timing_mode,
        day_timezone=settings.day_timezone,
        draws=settings.timing_draws,
        bootstrap_replications=settings.bootstrap_replications,
        mean_block_length=settings.mean_block_length,
        confidence_level=confidence,
        seed=child_seed(1),
    )

    tercile_options: dict[str, Any] = dict(
        bootstrap_replications=settings.bootstrap_replications,
        mean_block_length=settings.mean_block_length,
        confidence_level=confidence,
        permutation_draws=settings.permutation_draws,
    )
    holding_period = split_by_terciles(
        net,
        trades.holding_seconds / 3600.0,
        variable_name="holding_period_hours",
        source="trade_log",
        labels_text=("short", "medium", "long"),
        seed=child_seed(2),
        **tercile_options,
    )
    if trades.entry_volatility is not None:
        volatility, source = (
            trades.entry_volatility,
            "trade_log entry_volatility column",
        )
    elif prices is not None:
        volatility = trailing_volatility(
            trades, prices, settings.volatility_lookback_bars
        )
        source = (
            f"price file: SD of log changes over the {settings.volatility_lookback_bars} "
            "bars before entry"
        )
    else:
        volatility, source = np.full(count, np.nan), "none (no price file, no column)"
    volatility_regime = split_by_terciles(
        net,
        volatility,
        variable_name="entry_volatility",
        source=source,
        labels_text=("low", "mid", "high"),
        seed=child_seed(3),
        **tercile_options,
    )

    costs = analyse_costs(
        net,
        gross,
        notional,
        span_years=span_years,
        declared_trials=settings.declared_trials,
        confidence_level=confidence,
        trial_sharpe_std=settings.trial_sharpe_std,
        grid_bps=settings.cost_grid_bps,
        bootstrap_pnl_means=shared["expectancy"],
        bootstrap_notional_means=shared["notional"],
    )

    decay = analyse_decay(
        net,
        tuple(stamp.isoformat() for stamp in trades.exit_time),
        reference_trades=settings.reference_trades,
        shift_sigma=settings.decay_shift_sigma,
        false_alarm_probability=settings.decay_false_alarm_probability,
        horizon=settings.decay_horizon,
        rolling_window=settings.rolling_window,
        bootstrap_replications=settings.bootstrap_replications,
        mean_block_length=settings.mean_block_length,
        confidence_level=confidence,
        seed=child_seed(4),
    )

    sizing = analyse_sizing(
        net,
        notional,
        span_years=span_years,
        declared_trials=settings.declared_trials,
        confidence_level=confidence,
        trial_sharpe_std=settings.trial_sharpe_std,
        bootstrap=shared,
        actual_expectancy=expectancy_interval,
        permutation_draws=settings.permutation_draws,
        seed=child_seed(5),
    )

    return EdgeAuditResult(
        settings=settings,
        performance=performance,
        luck_vs_skill=luck,
        timing=timing,
        holding_period=holding_period,
        volatility_regime=volatility_regime,
        costs=costs,
        decay=decay,
        sizing=sizing,
        warnings=_warnings(trades, settings, performance, timing, decay),
    )


def _performance(
    trades: TradeLog,
    settings: AuditSettings,
    expectancy_interval: Interval,
    shared: dict[str, np.ndarray],
    span_years: float,
) -> PerformanceSummary:
    net = trades.net_pnl
    wins, losses = net[net > 0.0], net[net < 0.0]
    average_win = float(np.mean(wins)) if wins.size else None
    average_loss = float(np.mean(losses)) if losses.size else None
    confidence = settings.confidence_level
    serial = None
    if len(trades) > 10 and np.ptp(net) > 0.0:
        lag = min(10, len(trades) // 5)
        serial = calculate_serial_dependence(
            trade_clock_series(
                net, max(1, int(round(len(trades) / max(span_years, 1e-9))))
            ),
            spec=SerialDependenceSpec(
                maximum_lag=lag, significance_level=1 - confidence
            ),
        )
    return PerformanceSummary(
        trade_count=len(trades),
        winning_trades=int(wins.size),
        losing_trades=int(losses.size),
        flat_trades=int(np.sum(net == 0.0)),
        total_net_pnl=float(np.sum(net)),
        total_gross_pnl=float(np.sum(trades.gross_pnl)),
        total_fees=float(np.sum(trades.fees)),
        expectancy=expectancy_interval,
        profit_factor=percentile_interval(
            profit_factor(net), shared["profit_factor"], confidence_level=confidence
        ),
        win_rate=percentile_interval(
            win_rate(net), shared["win_rate"], confidence_level=confidence
        ),
        average_win=average_win,
        average_loss=average_loss,
        payoff_ratio=(
            average_win / -average_loss
            if average_win is not None and average_loss is not None
            else None
        ),
        mean_net_return_bps=float(np.mean(trades.net_return) * 1e4),
        median_holding_hours=float(np.median(trades.holding_seconds) / 3600.0),
        first_entry=trades.entry_time.min().isoformat(),
        last_exit=trades.exit_time.max().isoformat(),
        span_years=span_years,
        instruments=tuple(sorted(set(trades.instrument))),
        currency=trades.currency,
        max_concurrent_trades=_max_concurrent(trades),
        serial_dependence_p_value=None if serial is None else serial.p_value,
        lag_one_autocorrelation=(
            None
            if serial is None or not serial.autocorrelations
            else serial.autocorrelations[0].autocorrelation
        ),
    )


def _max_concurrent(trades: TradeLog) -> int:
    """Largest number of trades open at the same instant.

    A trade is open on [entry, exit); one exiting when another enters does
    not overlap it. A zero-length trade (entry = exit) is open for one
    nanosecond, so simultaneous zero-length trades count as concurrent.
    """

    entries = trades.entry_time.asi8
    exits = trades.exit_time.asi8
    exits = np.where(exits == entries, exits + 1, exits)
    events = np.concatenate([entries, exits])
    kinds = np.concatenate([np.ones(len(trades)), -np.ones(len(trades))])
    order = np.lexsort((kinds, events))  # at equal times, exits (-1) first
    return int(np.max(np.cumsum(kinds[order])))


def _warnings(
    trades: TradeLog,
    settings: AuditSettings,
    performance: PerformanceSummary,
    timing: TimingResult,
    decay: DecayResult,
) -> tuple[str, ...]:
    notes: list[str] = []
    if not trades.schema_declared:
        notes.append(
            "The trade file has no '# schema: edge-audit-trades/1.0' line; read as 1.0."
        )
    if len(trades) < 100:
        notes.append(
            f"Only {len(trades)} trades: intervals are wide and the bootstrap "
            "percentile interval tends to be too narrow at this size."
        )
    if (
        performance.serial_dependence_p_value is not None
        and performance.serial_dependence_p_value < 1 - settings.confidence_level
        and settings.mean_block_length == 1
    ):
        notes.append(
            "Trade P&L is serially dependent (Ljung-Box p = "
            f"{performance.serial_dependence_p_value:.3g}); the i.i.d. trade "
            "bootstrap and the DSR standard error assume independence. Re-run "
            "with --block-length > 1 and treat the verdict as optimistic."
        )
    if (
        performance.serial_dependence_p_value is not None
        and performance.serial_dependence_p_value < 1 - settings.confidence_level
        and decay.status == "computed"
    ):
        notes.append(
            "The decay detectors' thresholds assume independent trades; with "
            "serially dependent P&L (Ljung-Box p = "
            f"{performance.serial_dependence_p_value:.3g}) they raise false alarms "
            "more often than the stated α (docs/edge_audit/CALIBRATION.md, Table A)."
        )
    if performance.max_concurrent_trades > 1:
        notes.append(
            f"Up to {performance.max_concurrent_trades} trades were open at once; "
            "overlapping trades share market moves, so they are less independent "
            "than their count suggests."
        )
    if timing.status == "computed" and timing.excluded:
        dropped = sum(timing.excluded.values())
        reasons = ", ".join(
            f"{count} {reason.replace('_', ' ')}"
            for reason, count in sorted(timing.excluded.items())
        )
        notes.append(
            f"Timing decomposition covers {timing.covered_trades} of {len(trades)} "
            f"trades; {dropped} had no usable price window ({reasons})."
        )
    return tuple(notes)
