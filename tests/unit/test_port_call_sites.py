"""Guards for ported call sites that no test exercised.

The adversarial review reverted each ported line to its 1.5.0 form and ran the
suite; for the sites below nothing failed, because the tests that came with
the original commits test a helper function, not the line that calls it. Each
test here fails when its site is put back:

- parameter_robustness: `_within_radius(...)` -> `distance <= maximum_distance` (12aa60c)
- scripts/release_contracts.py: `_document_matches(...)` -> byte equality (6d7a1f0)
- cli._emit_report: the report_serialization_failed backstop (48731d1)
- performance_path: the CAGR overflow filter (48731d1)
- deflated_sharpe: the structural cross-trial spread (3a9795e)
- bootstrap._point_estimates: the structural point-estimate volatility (19a2eae)
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.release_contracts as release_contracts
from backtest_auditor.domain.assumptions import (
    BootstrapSpec,
    DeflatedSharpeRatioSpec,
    ParameterRobustnessSpec,
    ParameterScale,
    SharpeRatioSpec,
)
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    BootstrapMetric,
    DeflatedSharpeRatioMethod,
    DeflatedSharpeRatioStatus,
    DSRTrialCountPolicy,
    FrequencyStatus,
    ParameterDistanceMetric,
    ReturnConvention,
    RobustnessPerformanceMetric,
    SelectionDirection,
    TrialOutcome,
)
from backtest_auditor.domain.experiment import (
    ExperimentFamily,
    ExperimentFamilyManifest,
    ExperimentTrial,
    TrialParameter,
    TrialReturnMatrix,
)
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.statistics.annualized import calculate_annualized_statistics
from backtest_auditor.statistics.bootstrap import (
    calculate_bootstrap_confidence_intervals,
)
from backtest_auditor.statistics.deflated_sharpe import (
    calculate_deflated_sharpe_ratio,
)
from backtest_auditor.statistics.parameter_robustness import (
    calculate_parameter_robustness,
)
from backtest_auditor.statistics.performance_path import calculate_performance_path
from backtest_auditor.statistics.sampling import assess_sampling

REPO = Path(__file__).resolve().parents[2]


def _family(
    values: np.ndarray,
    parameters: tuple[float, ...],
    *,
    selected_index: int,
) -> ExperimentFamily:
    trial_ids = tuple(f"trial-{index + 1}" for index in range(values.shape[1]))
    trials = tuple(
        ExperimentTrial(
            trial_id=trial_id,
            attempt_index=index + 1,
            outcome=TrialOutcome.COMPLETED,
            included_in_selection=True,
            selected=index == selected_index,
            selection_score=(2.0 if index == selected_index else 1.0),
            parameters=(TrialParameter("threshold", parameters[index]),),
        )
        for index, trial_id in enumerate(trial_ids)
    )
    sampling = SamplingSpec(declared_frequency="B", periods_per_year=252)
    return ExperimentFamily(
        manifest=ExperimentFamilyManifest(
            schema_version="1.0",
            family_id="call-site-family",
            declared_total_attempted_trials=len(trial_ids),
            search_complete=True,
            selected_trial_id=trial_ids[selected_index],
            selection_rule="maximize period Sharpe",
            selection_metric="period_sharpe_ratio",
            selection_direction=SelectionDirection.MAXIMIZE,
            parameter_names=("threshold",),
            return_convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
        trials=trials,
        returns=TrialReturnMatrix(
            timestamps=pd.date_range("2026-01-01", periods=len(values), freq="B"),
            trial_ids=trial_ids,
            values=values,
            convention=ReturnConvention.SIMPLE,
            sampling=sampling,
        ),
    )


def test_decimal_grid_neighbourhood_is_symmetric_through_the_audit() -> None:
    """0.7 and 0.9 are both one 0.1-step from 0.8, so both are neighbours."""

    assert abs(0.7 - 0.8) / 0.1 > 1.0 > abs(0.9 - 0.8) / 0.1  # the float premise
    values = np.asarray(
        [
            [0.010, 0.012, 0.011],
            [-0.004, -0.002, -0.003],
            [0.006, 0.009, 0.007],
            [0.002, 0.004, 0.001],
            [0.008, 0.010, 0.009],
            [-0.001, 0.001, -0.002],
        ]
    )
    family = _family(values, (0.7, 0.8, 0.9), selected_index=1)
    spec = ParameterRobustnessSpec(
        performance_metric=RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
        selection_metric_name="period_sharpe_ratio",
        annual_risk_free_rate=0.0,
        distance_metric=ParameterDistanceMetric.STANDARDIZED_EUCLIDEAN,
        parameter_scales=(ParameterScale("threshold", 0.1),),
        maximum_distance=1.0,
        minimum_neighbor_count=2,
        maximum_acceptable_score_difference=100.0,
        minimum_acceptable_neighbor_fraction=1.0,
    )

    result = calculate_parameter_robustness(family, spec)

    assert [item.trial_id for item in result.neighbors] == ["trial-1", "trial-3"]
    assert result.neighbor_count == 2


def test_golden_check_accepts_last_bit_noise_and_rejects_real_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_contracts, "ROOT", tmp_path)
    value = 0.0003775510204081632
    golden = tmp_path / "golden.json"
    golden.write_text(release_contracts._render_json({"alpha": value}))

    noise = value + 3 * math.ulp(value)
    change = value * (1 + 1e-9)

    assert (
        release_contracts._check_documents(
            {golden: release_contracts._render_json({"alpha": noise})}
        )
        == 0
    )
    assert (
        release_contracts._check_documents(
            {golden: release_contracts._render_json({"alpha": change})}
        )
        != 0
    )


def test_unserialisable_report_ends_in_the_json_error_envelope(tmp_path: Path) -> None:
    """1.4.0's gross/net evidence still overflows to inf (not fixed in 1.5.1);
    the 48731d1 backstop must turn that into exit 4 with an envelope."""

    rows = "".join(f"2026-01-0{day},1e308\n" for day in range(1, 5))
    returns = tmp_path / "returns.csv"
    gross = tmp_path / "gross.csv"
    returns.write_text("timestamp,return\n" + rows)
    gross.write_text("timestamp,return\n" + rows)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtest_auditor.cli",
            str(returns),
            "--run-id",
            "overflow-gross",
            "--gross-returns-csv",
            str(gross),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 4, result.stderr
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stderr.strip().splitlines()[-1])
    assert payload["error"] == "report_serialization_failed"


def test_cagr_that_overflows_is_reported_as_undefined() -> None:
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=3, freq="D"),
        values=np.asarray([1.0, 1.0, 1.0]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(declared_frequency="D", periods_per_year=1_000_000),
    )
    sampling = assess_sampling(series)
    assert sampling.annualization_eligible

    result = calculate_performance_path(series, sampling)

    assert result.ending_wealth == 8.0
    assert result.cagr is None


def test_identical_trials_have_exactly_zero_cross_trial_spread() -> None:
    returns = [-0.0044, -0.0022, 0.0051, 0.0114, -0.0003, 0.0147, -0.0057, 0.0045]
    values = np.column_stack([returns] * 3)
    family = _family(values, (0.7, 0.8, 0.9), selected_index=0)
    spec = DeflatedSharpeRatioSpec(
        method=DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
        trial_count_policy=DSRTrialCountPolicy.SELECTION_ELIGIBLE,
        annual_risk_free_rate=0.0,
        required_confidence_level=0.95,
    )

    result = calculate_deflated_sharpe_ratio(family, spec)

    sharpes = [item.period_sharpe_ratio for item in result.trial_sharpe_estimates]
    assert float(np.std(sharpes, ddof=1)) != 0.0  # the residue exists
    assert result.status is DeflatedSharpeRatioStatus.ELIGIBLE
    assert result.cross_trial_sample_standard_deviation == 0.0
    assert all(
        scenario.expected_maximum_period_sharpe_ratio == 0.0
        for scenario in result.scenarios
    )


def test_constant_series_bootstrap_point_estimates_are_structural() -> None:
    values = np.full(10, 0.001)
    assert float(np.std(values, ddof=1)) != 0.0  # the residue exists
    series = ReturnSeries(
        timestamps=pd.date_range("2026-01-01", periods=len(values), freq="D"),
        values=values,
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(
            status=FrequencyStatus.DECLARED,
            declared_frequency="D",
            periods_per_year=252,
        ),
    )
    sampling = assess_sampling(series)
    annualized = calculate_annualized_statistics(
        series, sampling, sharpe_spec=SharpeRatioSpec(annual_risk_free_rate=0.0)
    )

    result = calculate_bootstrap_confidence_intervals(
        series,
        sampling,
        annualized,
        None,
        spec=BootstrapSpec(
            method=BootstrapMethod.MOVING_BLOCK,
            interval_method=BootstrapIntervalMethod.PERCENTILE,
            replications=50,
            confidence_level=0.9,
            block_length=2,
            random_seed=1,
        ),
    )

    assert result is not None
    by_metric = {item.metric: item for item in result.metrics}
    assert by_metric[BootstrapMetric.PERIOD_SAMPLE_VOLATILITY].point_estimate == 0.0
    assert by_metric[BootstrapMetric.PERIOD_SHARPE_RATIO].point_estimate is None
