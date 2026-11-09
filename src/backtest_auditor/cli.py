import argparse
import json
import math
import os
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from backtest_auditor.application.ibkr_flex_import import (
    IbkrFlexImportContext,
    import_ibkr_flex_payloads,
)

from backtest_auditor.application.experiment_family_audit import (
    ExperimentFamilyAuditResult,
    audit_experiment_family,
)
from backtest_auditor.application.single_run_audit import (
    SingleRunAuditResult,
    audit_single_run,
)
from backtest_auditor.domain.assumptions import (
    AdvancedRiskSpec,
    BenchmarkInferenceSpec,
    BootstrapSpec,
    CSCVSpec,
    DeflatedSharpeRatioSpec,
    DataSnoopingSpec,
    ParameterRobustnessSpec,
    ParameterScale,
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
    SharpeRatioSpec,
    TemporalRobustnessSpec,
)
from backtest_auditor.domain.enums import (
    BootstrapIntervalMethod,
    BootstrapMethod,
    CSCVMethod,
    CSCVPerformanceMetric,
    CSCVRankTieMethod,
    CSCVWinnerTiePolicy,
    DeflatedSharpeRatioMethod,
    DSRTrialCountPolicy,
    FrequencyStatus,
    HACKernel,
    ParameterDistanceMetric,
    LeveragePolicy,
    PriceAdjustmentPolicy,
    ReturnConvention,
    RobustnessPerformanceMetric,
    RobustnessRankTieMethod,
    RobustnessWinnerTiePolicy,
)
from backtest_auditor.domain.issues import (
    InputValidationError,
    ValidationIssue,
)
from backtest_auditor.domain.metadata import (
    ObservationCalendarSpec,
    ReturnConstructionSpec,
)
from backtest_auditor.domain.reproducibility import AuditRunSpec
from backtest_auditor.domain.runs import BenchmarkRun, StrategyRun
from backtest_auditor.domain.series import SamplingSpec
from backtest_auditor.ingestion.calendar_sessions import (
    read_calendar_session_dates_csv,
)
from backtest_auditor.ingestion.csv_returns import (
    read_return_series_csv,
)
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)
from backtest_auditor.ingestion.file_hashing import hash_input_file
from backtest_auditor.ingestion.ibkr_flex import (
    IBKR_FLEX_DATE_FORMATS,
    IbkrFlexPayload,
    IbkrFlexSelection,
    load_ibkr_flex_files,
)
from backtest_auditor.ingestion.regimes import read_regime_series_csv
from backtest_auditor.integrations.ibkr_flex import (
    FlexWebServiceClient,
    IbkrFlexCredentials,
    IbkrFlexError,
    IbkrFlexRequest,
)
from backtest_auditor.reporting.json_report import (
    render_json_report,
)
from backtest_auditor.reporting.markdown_report import (
    render_markdown_report,
)
from backtest_auditor.reporting.serialization import (
    validation_issue_to_dict,
)
from backtest_auditor.implementation_risk import (
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditResult,
    ImplementationRiskAuditService,
    comparison_policy_from_json,
    divergence_policy_from_json,
    load_policy_json_file,
    normalization_plan_from_json,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_from_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backtest-auditor",
        description=("Audit a timestamped return series from a CSV file."),
        epilog=(
            "Use 'backtest-auditor family --help' or "
            "'backtest-auditor implementation-risk --help' for other workflows."
        ),
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--timestamp-column",
        default="timestamp",
    )
    parser.add_argument(
        "--return-column",
        default="return",
    )
    parser.add_argument(
        "--return-convention",
        choices=[item.value for item in ReturnConvention],
        default=ReturnConvention.SIMPLE.value,
    )
    parser.add_argument(
        "--declared-frequency",
        type=_declared_frequency,
        help=("Declared pandas offset alias, such as D, B, W, ME, or h."),
    )
    parser.add_argument(
        "--periods-per-year",
        type=_positive_integer,
        help=("Explicit annualization scale; no default is assumed."),
    )
    parser.add_argument(
        "--annual-risk-free-rate",
        type=_annual_risk_free_rate,
        help=(
            "Effective annual simple risk-free rate as a decimal; "
            "required for Sharpe and never assumed."
        ),
    )
    parser.add_argument(
        "--benchmark-annualized-sharpe-ratio",
        type=_finite_number,
        help=("Explicit annualized Sharpe benchmark for PSR; no default is assumed."),
    )
    parser.add_argument(
        "--required-psr-confidence-level",
        type=_confidence_level_above_half,
        help=(
            "Explicit PSR evidence requirement strictly between "
            "0.5 and 1.0; required for minimum track-record length."
        ),
    )
    parser.add_argument(
        "--serial-max-lag",
        type=_positive_integer,
        help=(
            "Explicit maximum lag for the Ljung-Box serial-"
            "dependence diagnostic; no default is assumed."
        ),
    )
    parser.add_argument(
        "--serial-significance-level",
        type=_probability,
        help=(
            "Explicit significance level strictly between 0 and 1 "
            "for the Ljung-Box decision; no default is assumed."
        ),
    )
    parser.add_argument(
        "--hac-max-lag",
        type=_positive_integer,
        help=(
            "Explicit maximum lag (bandwidth) for the serial-"
            "dependence adjustment; no default is assumed."
        ),
    )
    parser.add_argument(
        "--hac-kernel",
        choices=[item.value for item in HACKernel],
        help=(
            "Explicit HAC kernel for the serial-dependence "
            "adjustment; currently bartlett."
        ),
    )
    parser.add_argument(
        "--bootstrap-method",
        choices=[item.value for item in BootstrapMethod],
        help=("Explicit time-series bootstrap method: moving_block or stationary."),
    )
    parser.add_argument(
        "--bootstrap-interval-method",
        choices=[item.value for item in BootstrapIntervalMethod],
        help=("Explicit confidence-interval construction; currently percentile."),
    )
    parser.add_argument(
        "--bootstrap-replications",
        type=_integer_at_least_two,
        help=("Explicit number of bootstrap replications; no default is assumed."),
    )
    parser.add_argument(
        "--bootstrap-confidence-level",
        type=_confidence_level_above_half,
        help=(
            "Explicit two-sided bootstrap confidence level strictly "
            "between 0.5 and 1.0."
        ),
    )
    parser.add_argument(
        "--bootstrap-block-length",
        type=_positive_integer,
        help=(
            "Explicit fixed block length for moving_block, or mean block length "
            "for stationary; no automatic selection is performed."
        ),
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=_non_negative_integer,
        help=("Explicit non-negative random seed for reproducible resampling."),
    )
    parser.add_argument("--minimum-acceptable-period-return", type=_finite_number)
    parser.add_argument(
        "--tail-confidence-level",
        type=_confidence_level_above_half,
    )
    parser.add_argument("--risk-free-csv", type=Path)
    parser.add_argument("--risk-free-timestamp-column", default="timestamp")
    parser.add_argument("--risk-free-return-column", default="return")
    parser.add_argument(
        "--risk-free-return-convention",
        choices=[item.value for item in ReturnConvention],
        default=ReturnConvention.SIMPLE.value,
    )
    parser.add_argument("--gross-returns-csv", type=Path)
    parser.add_argument("--gross-timestamp-column", default="timestamp")
    parser.add_argument("--gross-return-column", default="return")
    parser.add_argument(
        "--gross-return-convention",
        choices=[item.value for item in ReturnConvention],
        default=ReturnConvention.SIMPLE.value,
    )
    parser.add_argument("--regimes-csv", type=Path)
    parser.add_argument("--regime-timestamp-column", default="timestamp")
    parser.add_argument("--regime-column", default="regime")
    parser.add_argument("--benchmark-alpha-hac-max-lag", type=_non_negative_integer)
    parser.add_argument(
        "--benchmark-alpha-confidence-level",
        type=_confidence_level_above_half,
    )
    parser.add_argument(
        "--timestamp-timezone",
        help=(
            "IANA timezone in which naive strategy timestamps should be interpreted."
        ),
    )
    parser.add_argument("--observation-calendar")
    parser.add_argument("--calendar-timezone")
    parser.add_argument("--calendar-sessions-csv", type=Path)
    parser.add_argument(
        "--calendar-session-column",
        default="session",
    )
    _add_return_construction_arguments(parser)

    parser.add_argument("--benchmark-csv", type=Path)
    parser.add_argument("--benchmark-id")
    parser.add_argument(
        "--benchmark-timestamp-column",
        default="timestamp",
    )
    parser.add_argument(
        "--benchmark-return-column",
        default="return",
    )
    parser.add_argument(
        "--benchmark-return-convention",
        choices=[item.value for item in ReturnConvention],
        default=ReturnConvention.SIMPLE.value,
    )
    parser.add_argument("--benchmark-timestamp-timezone")
    parser.add_argument("--benchmark-observation-calendar")
    parser.add_argument("--benchmark-calendar-timezone")
    parser.add_argument("--benchmark-calendar-sessions-csv", type=Path)
    parser.add_argument(
        "--benchmark-calendar-session-column",
        default="session",
    )
    _add_return_construction_arguments(parser, prefix="benchmark")
    _add_run_manifest_arguments(parser)
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the report to this path instead of stdout.",
    )
    return parser


def build_family_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backtest-auditor family",
        description=(
            "Audit a canonical experiment-family manifest, trial table, "
            "and aligned long-format return matrix."
        ),
    )
    parser.add_argument("manifest_json", type=Path)
    parser.add_argument("trials_csv", type=Path)
    parser.add_argument("returns_csv", type=Path)
    parser.add_argument(
        "--splits-csv",
        type=Path,
        help=(
            "Optional canonical split-membership CSV with split_id, "
            "timestamp, and role columns."
        ),
    )
    parser.add_argument(
        "--benchmark-csv",
        type=Path,
        help=(
            "Optional shared benchmark CSV. Its ID and return convention "
            "must be declared in the manifest."
        ),
    )
    parser.add_argument(
        "--dsr-method",
        choices=[item.value for item in DeflatedSharpeRatioMethod],
        help="Explicit DSR method; currently classic_expected_maximum.",
    )
    parser.add_argument(
        "--dsr-trial-count-policy",
        choices=[item.value for item in DSRTrialCountPolicy],
        help=("Explicit primary trial-count policy; currently selection_eligible."),
    )
    parser.add_argument(
        "--dsr-annual-risk-free-rate",
        type=_annual_risk_free_rate,
        help=(
            "Effective annual simple risk-free rate used for every family "
            "Sharpe estimate."
        ),
    )
    parser.add_argument(
        "--dsr-confidence-level",
        type=_confidence_level_above_half,
        help=("Explicit DSR evidence requirement strictly between 0.5 and 1.0."),
    )
    parser.add_argument(
        "--dsr-effective-independent-trials",
        type=_positive_integer,
        help=(
            "Optional externally justified effective independent-trial "
            "count; requires a methodology statement."
        ),
    )
    parser.add_argument(
        "--dsr-effective-trial-count-methodology",
        help=(
            "Methodology statement supporting the optional effective "
            "independent-trial count."
        ),
    )
    parser.add_argument(
        "--cscv-method",
        choices=[item.value for item in CSCVMethod],
        help="Explicit CSCV method; currently combinatorially_symmetric.",
    )
    parser.add_argument(
        "--cscv-performance-metric",
        choices=[item.value for item in CSCVPerformanceMetric],
        help="Explicit split performance metric; currently period_sharpe_ratio.",
    )
    parser.add_argument(
        "--cscv-selection-metric-name",
        help="Exact manifest selection_metric confirmed as equivalent to the CSCV metric.",
    )
    parser.add_argument(
        "--cscv-partitions",
        type=_even_integer_at_least_two,
        help="Explicit even number of equal contiguous partitions.",
    )
    parser.add_argument(
        "--cscv-annual-risk-free-rate",
        type=_annual_risk_free_rate,
        help="Effective annual simple risk-free rate for every split Sharpe.",
    )
    parser.add_argument(
        "--cscv-maximum-combinations",
        type=_positive_integer,
        help="Explicit safety limit; CSCV remains unavailable rather than sampled.",
    )
    parser.add_argument(
        "--cscv-rank-tie-method",
        choices=[item.value for item in CSCVRankTieMethod],
        help="Explicit OOS rank tie method; currently average.",
    )
    parser.add_argument(
        "--cscv-winner-tie-policy",
        choices=[item.value for item in CSCVWinnerTiePolicy],
        help="Explicit IS winner tie policy; currently first_by_attempt_index.",
    )
    parser.add_argument(
        "--cscv-maximum-acceptable-pbo",
        type=_probability,
        help="Explicit maximum acceptable PBO strictly between 0 and 1.",
    )
    parser.add_argument(
        "--parameter-robustness-metric",
        choices=[item.value for item in RobustnessPerformanceMetric],
        help="Explicit local-neighborhood metric; currently period_sharpe_ratio.",
    )
    parser.add_argument(
        "--parameter-selection-metric-name",
        help="Exact manifest selection_metric confirmed as the robustness metric.",
    )
    parser.add_argument(
        "--parameter-annual-risk-free-rate",
        type=_annual_risk_free_rate,
        help="Effective annual simple risk-free rate for neighborhood Sharpes.",
    )
    parser.add_argument(
        "--parameter-distance-metric",
        choices=[item.value for item in ParameterDistanceMetric],
        help="Explicit neighborhood geometry; currently standardized_euclidean.",
    )
    parser.add_argument(
        "--parameter-scale",
        action="append",
        type=_parameter_scale,
        metavar="NAME=VALUE",
        help="Positive scale for one numeric parameter; repeat in name order.",
    )
    parser.add_argument(
        "--parameter-maximum-distance",
        type=_positive_finite_number,
        help="Inclusive standardized radius around the selected configuration.",
    )
    parser.add_argument(
        "--parameter-minimum-neighbors",
        type=_positive_integer,
        help="Minimum in-radius tested configurations required for interpretation.",
    )
    parser.add_argument(
        "--parameter-maximum-score-difference",
        type=_non_negative_finite_number,
        help="Maximum absolute period-Sharpe difference counted as plateau-like.",
    )
    parser.add_argument(
        "--parameter-minimum-acceptable-neighbor-fraction",
        type=_inclusive_probability,
        help="Required plateau-like neighbor fraction between 0 and 1 inclusive.",
    )
    parser.add_argument(
        "--temporal-robustness-metric",
        choices=[item.value for item in RobustnessPerformanceMetric],
        help="Explicit equal-window and declared-split metric.",
    )
    parser.add_argument(
        "--temporal-selection-metric-name",
        help="Exact manifest selection_metric confirmed as the temporal metric.",
    )
    parser.add_argument(
        "--temporal-annual-risk-free-rate",
        type=_annual_risk_free_rate,
        help="Effective annual simple risk-free rate for all temporal Sharpes.",
    )
    parser.add_argument(
        "--temporal-windows",
        type=_integer_at_least_two,
        help="Explicit count of equal contiguous windows; no remainder is trimmed.",
    )
    parser.add_argument(
        "--temporal-rank-tie-method",
        choices=[item.value for item in RobustnessRankTieMethod],
        help="Explicit window/OOS rank tie method; currently average.",
    )
    parser.add_argument(
        "--temporal-winner-tie-policy",
        choices=[item.value for item in RobustnessWinnerTiePolicy],
        help="Explicit declared-split IS tie policy; currently first_by_attempt_index.",
    )
    parser.add_argument(
        "--temporal-minimum-acceptable-top-half-fraction",
        type=_inclusive_probability,
        help="Required selected-trial top-half window fraction, inclusive 0 to 1.",
    )
    parser.add_argument(
        "--temporal-maximum-acceptable-below-zero-fraction",
        type=_inclusive_probability,
        help="Maximum selected-trial below-zero window fraction, inclusive 0 to 1.",
    )
    parser.add_argument("--data-snooping-replications", type=_integer_at_least_two)
    parser.add_argument("--data-snooping-mean-block-length", type=_positive_integer)
    parser.add_argument("--data-snooping-seed", type=_non_negative_integer)
    parser.add_argument("--data-snooping-significance-level", type=_probability)
    _add_run_manifest_arguments(parser)
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the report to this path instead of stdout.",
    )
    return parser


def build_ibkr_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backtest-auditor ibkr",
        description=(
            "Import IBKR Activity Flex Change-in-NAV TWR intervals into the "
            "canonical Single-Run CSV contract."
        ),
        epilog=(
            "The API token is accepted only through BACKTEST_AUDITOR_IBKR_FLEX_TOKEN."
        ),
    )
    subparsers = parser.add_subparsers(dest="ibkr_source", required=True)
    files_parser = subparsers.add_parser(
        "files",
        help="Import one or more exported XML/CSV Activity Flex statements.",
    )
    files_parser.add_argument("statements", nargs="+", type=Path)
    _add_ibkr_import_arguments(files_parser)

    api_parser = subparsers.add_parser(
        "api",
        help="Fetch one configured query through read-only Flex Web Service v3.",
    )
    api_parser.add_argument(
        "--query-id",
        help=(
            "Configured Activity Flex query ID. Falls back to "
            "BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID."
        ),
    )
    api_parser.add_argument("--from-date", type=_iso_date)
    api_parser.add_argument("--to-date", type=_iso_date)
    api_parser.add_argument(
        "--timeout-seconds",
        type=_positive_finite_number,
        default=30.0,
    )
    api_parser.add_argument(
        "--maximum-poll-attempts",
        type=_positive_integer,
        default=10,
    )
    api_parser.add_argument(
        "--minimum-request-interval-seconds",
        type=_positive_finite_number,
        default=6.1,
        help="Must be at least 6 seconds to honor the documented token rate limit.",
    )
    _add_ibkr_import_arguments(api_parser)
    return parser


def build_implementation_risk_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backtest-auditor implementation-risk",
        description=(
            "Compare one canonical reference bundle with one or more canonical "
            "candidate bundles under four explicit V1.5 policies."
        ),
    )
    parser.add_argument("reference_bundle", type=Path)
    parser.add_argument("candidate_bundles", nargs="+", type=Path)
    parser.add_argument("--normalization-plan", type=Path, required=True)
    parser.add_argument("--comparison-policy", type=Path, required=True)
    parser.add_argument("--measurement-policy", type=Path, required=True)
    parser.add_argument("--assessment-policy", type=Path, required=True)
    _add_run_manifest_arguments(parser)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Atomically replace an existing report output.",
    )
    return parser


def _add_ibkr_import_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="Default: OUTPUT with suffix .ibkr-import.json.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--account-id",
        help="Required only when the statements contain multiple account scopes.",
    )
    parser.add_argument(
        "--model",
        help="Optional model selector; requires --account-id.",
    )
    parser.add_argument(
        "--date-format",
        choices=tuple(IBKR_FLEX_DATE_FORMATS),
        default="yyyyMMdd",
        help="Must match the Activity Flex query's configured date format.",
    )
    parser.add_argument("--declared-frequency", type=_declared_frequency)
    parser.add_argument("--periods-per-year", type=_positive_integer)


def _add_run_manifest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--audit-id",
        type=_non_empty_text,
        help=(
            "Explicit stable identifier for this audit execution; requires "
            "--audit-timestamp and --git-commit."
        ),
    )
    parser.add_argument(
        "--audit-timestamp",
        type=_audit_timestamp,
        help=(
            "Explicit timezone-aware ISO 8601 audit timestamp. Current time is "
            "never inferred."
        ),
    )
    parser.add_argument(
        "--git-commit",
        type=_non_empty_text,
        help=(
            "Explicit Git revision or other source identity for the executed code; "
            "the supplied value is recorded but not inferred or verified."
        ),
    )


def _add_return_construction_arguments(
    parser: argparse.ArgumentParser,
    *,
    prefix: str | None = None,
) -> None:
    option_prefix = "" if prefix is None else f"{prefix}-"
    destination_prefix = "" if prefix is None else f"{prefix}_"

    parser.add_argument(
        f"--{option_prefix}transaction-costs-included",
        dest=f"{destination_prefix}transaction_costs_included",
        type=_explicit_boolean,
        metavar="true|false",
    )
    parser.add_argument(
        f"--{option_prefix}fees-included",
        dest=f"{destination_prefix}fees_included",
        type=_explicit_boolean,
        metavar="true|false",
    )
    parser.add_argument(
        f"--{option_prefix}leverage-policy",
        dest=f"{destination_prefix}leverage_policy",
        choices=[item.value for item in LeveragePolicy],
    )
    parser.add_argument(
        f"--{option_prefix}currency",
        dest=f"{destination_prefix}currency",
    )
    parser.add_argument(
        f"--{option_prefix}price-adjustment-policy",
        dest=f"{destination_prefix}price_adjustment_policy",
        choices=[item.value for item in PriceAdjustmentPolicy],
    )
    parser.add_argument(
        f"--{option_prefix}data-source",
        dest=f"{destination_prefix}data_source",
    )
    parser.add_argument(
        f"--{option_prefix}data-vintage",
        dest=f"{destination_prefix}data_vintage",
    )
    parser.add_argument(
        f"--{option_prefix}stale-price-policy",
        dest=f"{destination_prefix}stale_price_policy",
    )
    parser.add_argument(
        f"--{option_prefix}delisting-return-policy",
        dest=f"{destination_prefix}delisting_return_policy",
    )
    parser.add_argument(
        f"--{option_prefix}survivorship-bias-controlled",
        dest=f"{destination_prefix}survivorship_bias_controlled",
        type=_explicit_boolean,
        metavar="true|false",
    )
    parser.add_argument(
        f"--{option_prefix}lookahead-bias-controlled",
        dest=f"{destination_prefix}lookahead_bias_controlled",
        type=_explicit_boolean,
        metavar="true|false",
    )
    parser.add_argument(
        f"--{option_prefix}signal-timing",
        dest=f"{destination_prefix}signal_timing",
    )
    parser.add_argument(
        f"--{option_prefix}execution-timing",
        dest=f"{destination_prefix}execution_timing",
    )


def _declared_frequency(value: str) -> str:
    try:
        canonical_frequency = SamplingSpec(declared_frequency=value).declared_frequency
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error

    assert canonical_frequency is not None
    return canonical_frequency


def _positive_integer(value: str) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be a positive integer") from error

    if parsed_value <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")

    return parsed_value


def _integer_at_least_two(value: str) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "value must be an integer greater than or equal to 2"
        ) from error

    if parsed_value < 2:
        raise argparse.ArgumentTypeError(
            "value must be an integer greater than or equal to 2"
        )

    return parsed_value


def _even_integer_at_least_two(value: str) -> int:
    parsed_value = _integer_at_least_two(value)
    if parsed_value % 2 != 0:
        raise argparse.ArgumentTypeError(
            "value must be an even integer greater than or equal to 2"
        )
    return parsed_value


def _non_negative_integer(value: str) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "value must be a non-negative integer"
        ) from error

    if parsed_value < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")

    return parsed_value


def _annual_risk_free_rate(value: str) -> float:
    try:
        parsed_value = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "value must be a finite number greater than -1.0"
        ) from error

    if not math.isfinite(parsed_value) or parsed_value <= -1.0:
        raise argparse.ArgumentTypeError(
            "value must be a finite number greater than -1.0"
        )

    return parsed_value


def _finite_number(value: str) -> float:
    try:
        parsed_value = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be a finite number") from error

    if not math.isfinite(parsed_value):
        raise argparse.ArgumentTypeError("value must be a finite number")

    return parsed_value


def _confidence_level_above_half(value: str) -> float:
    parsed_value = _finite_number(value)
    if parsed_value <= 0.5 or parsed_value >= 1.0:
        raise argparse.ArgumentTypeError("value must be strictly between 0.5 and 1.0")

    return parsed_value


def _probability(value: str) -> float:
    parsed_value = _finite_number(value)
    if parsed_value <= 0.0 or parsed_value >= 1.0:
        raise argparse.ArgumentTypeError("value must be strictly between 0.0 and 1.0")

    return parsed_value


def _inclusive_probability(value: str) -> float:
    parsed_value = _finite_number(value)
    if parsed_value < 0.0 or parsed_value > 1.0:
        raise argparse.ArgumentTypeError("value must be between 0.0 and 1.0 inclusive")
    return parsed_value


def _positive_finite_number(value: str) -> float:
    parsed_value = _finite_number(value)
    if parsed_value <= 0.0:
        raise argparse.ArgumentTypeError("value must be greater than 0.0")
    return parsed_value


def _non_negative_finite_number(value: str) -> float:
    parsed_value = _finite_number(value)
    if parsed_value < 0.0:
        raise argparse.ArgumentTypeError("value must be greater than or equal to 0.0")
    return parsed_value


def _parameter_scale(value: str) -> ParameterScale:
    name, separator, raw_scale = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("value must use NAME=VALUE syntax")
    try:
        return ParameterScale(name=name, scale=float(raw_scale))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _explicit_boolean(value: str) -> bool:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("value must be true or false")


def _audit_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "value must be a valid ISO 8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "value must include a timezone offset, such as Z or +02:00"
        )
    return parsed


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an ISO date (YYYY-MM-DD)") from error


def _non_empty_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("value must not be empty")
    return normalized


def _run_manifest_spec_from_arguments(
    parser: argparse.ArgumentParser,
    arguments: argparse.Namespace,
) -> AuditRunSpec | None:
    values = (
        arguments.audit_id,
        arguments.audit_timestamp,
        arguments.git_commit,
    )
    if any(value is not None for value in values) and not all(
        value is not None for value in values
    ):
        parser.error(
            "--audit-id, --audit-timestamp, and --git-commit must be supplied together"
        )
    if arguments.audit_id is None:
        return None
    return AuditRunSpec(
        audit_id=arguments.audit_id,
        audit_timestamp=arguments.audit_timestamp,
        git_commit=arguments.git_commit,
    )


def _calendar_spec_from_arguments(
    arguments: argparse.Namespace,
    *,
    prefix: str | None = None,
) -> ObservationCalendarSpec | None:
    name = getattr(
        arguments,
        "observation_calendar" if prefix is None else f"{prefix}_observation_calendar",
    )
    if name is None:
        return None

    timezone = getattr(
        arguments,
        "calendar_timezone" if prefix is None else f"{prefix}_calendar_timezone",
    )
    session_csv = getattr(
        arguments,
        "calendar_sessions_csv"
        if prefix is None
        else f"{prefix}_calendar_sessions_csv",
    )
    session_column = getattr(
        arguments,
        "calendar_session_column"
        if prefix is None
        else f"{prefix}_calendar_session_column",
    )
    session_dates = (
        None
        if session_csv is None
        else read_calendar_session_dates_csv(
            session_csv,
            session_column=session_column,
        )
    )
    return ObservationCalendarSpec(
        calendar_name=name,
        timezone=timezone,
        expected_session_dates=session_dates,
    )


def _return_construction_from_arguments(
    arguments: argparse.Namespace,
    *,
    prefix: str | None = None,
) -> ReturnConstructionSpec | None:
    field_names = (
        "transaction_costs_included",
        "fees_included",
        "leverage_policy",
        "currency",
        "price_adjustment_policy",
        "data_source",
        "data_vintage",
        "stale_price_policy",
        "delisting_return_policy",
        "survivorship_bias_controlled",
        "lookahead_bias_controlled",
        "signal_timing",
        "execution_timing",
    )
    destination_prefix = "" if prefix is None else f"{prefix}_"
    values = {
        field_name: getattr(
            arguments,
            f"{destination_prefix}{field_name}",
        )
        for field_name in field_names
    }
    if all(value is None for value in values.values()):
        return None
    return ReturnConstructionSpec(**values)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "implementation-risk":
        return _main_implementation_risk(arguments[1:])
    if arguments and arguments[0] == "family":
        return _main_family(arguments[1:])
    if arguments and arguments[0] == "ibkr":
        return _main_ibkr(arguments[1:])
    if arguments and arguments[0] == "single":
        return _main_single(arguments[1:])
    return _main_single(arguments)


def _main_implementation_risk(argv: Sequence[str]) -> int:
    parser = build_implementation_risk_parser()
    arguments = parser.parse_args(argv)
    source_paths = (
        arguments.reference_bundle,
        *arguments.candidate_bundles,
        arguments.normalization_plan,
        arguments.comparison_policy,
        arguments.measurement_policy,
        arguments.assessment_policy,
    )
    _validate_implementation_risk_output(
        parser,
        arguments.output,
        source_paths,
        force=arguments.force,
    )
    run_manifest_spec = _run_manifest_spec_from_arguments(parser, arguments)
    try:
        adapter = CanonicalArtifactFileBundleAdapter()
        artifacts = tuple(
            adapter.read(path)
            for path in (arguments.reference_bundle, *arguments.candidate_bundles)
        )
        normalization_plan = normalization_plan_from_json(
            load_policy_json_file(arguments.normalization_plan)
        )
        comparison_policy = comparison_policy_from_json(
            load_policy_json_file(arguments.comparison_policy)
        )
        measurement_policy = divergence_policy_from_json(
            load_policy_json_file(arguments.measurement_policy)
        )
        assessment_policy = risk_policy_from_json(
            load_policy_json_file(arguments.assessment_policy)
        )
        result = ImplementationRiskAuditService(adapter).audit(
            artifacts,
            normalization_plan,
            comparison_policy,
            measurement_policy,
            assessment_policy,
            run_manifest_spec=run_manifest_spec,
        )
    except (OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "error": "implementation_risk_audit_failed",
                    "message": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    return _emit_implementation_risk_report(
        result,
        report_format=arguments.format,
        output=arguments.output,
    )


def _validate_implementation_risk_output(
    parser: argparse.ArgumentParser,
    output: Path | None,
    sources: tuple[Path, ...],
    *,
    force: bool,
) -> None:
    if output is None:
        if force:
            parser.error("--force requires --output")
        return
    if output.is_symlink():
        parser.error("implementation-risk output must not be a symbolic link")
    if output.exists() and not output.is_file():
        parser.error("implementation-risk output must be a regular file path")
    if output.exists() and not force:
        parser.error(
            "refusing to overwrite existing implementation-risk output; "
            "use --force explicitly"
        )
    if not output.parent.is_dir():
        parser.error("implementation-risk output parent directory must exist")
    resolved = output.resolve()
    if any(resolved == source.resolve() for source in sources):
        parser.error("implementation-risk output must not replace an input file")


def _main_ibkr(argv: Sequence[str]) -> int:
    parser = build_ibkr_parser()
    arguments = parser.parse_args(argv)
    if arguments.model is not None and arguments.account_id is None:
        parser.error("--model requires --account-id")
    if (getattr(arguments, "from_date", None) is None) != (
        getattr(arguments, "to_date", None) is None
    ):
        parser.error("--from-date and --to-date must be supplied together")

    output = arguments.output
    manifest_output = arguments.manifest_output or output.with_suffix(
        ".ibkr-import.json"
    )
    if output.resolve() == manifest_output.resolve():
        parser.error("--output and --manifest-output must identify different files")
    existing = tuple(path for path in (output, manifest_output) if path.exists())
    if existing and not arguments.force:
        parser.error(
            "refusing to overwrite existing import output; use --force explicitly"
        )
    if not output.parent.is_dir() or not manifest_output.parent.is_dir():
        parser.error("import output parent directories must already exist")

    try:
        if arguments.ibkr_source == "files":
            payloads = load_ibkr_flex_files(arguments.statements)
            context = IbkrFlexImportContext(source_mode="files")
        else:
            token = os.environ.get("BACKTEST_AUDITOR_IBKR_FLEX_TOKEN", "")
            query_id = arguments.query_id or os.environ.get(
                "BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID", ""
            )
            if not token:
                parser.error(
                    "BACKTEST_AUDITOR_IBKR_FLEX_TOKEN is required for API import"
                )
            if not query_id:
                parser.error(
                    "--query-id or BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID is required"
                )
            client = FlexWebServiceClient(
                timeout_seconds=arguments.timeout_seconds,
                maximum_poll_attempts=arguments.maximum_poll_attempts,
                minimum_interval_seconds=(arguments.minimum_request_interval_seconds),
            )
            body = client.fetch_statement(
                IbkrFlexCredentials(token=token, query_id=query_id),
                IbkrFlexRequest(arguments.from_date, arguments.to_date),
            )
            payloads = (IbkrFlexPayload("ibkr-flex-api-response", body),)
            context = IbkrFlexImportContext(
                source_mode="api",
                query_id=query_id,
                requested_from_date=arguments.from_date,
                requested_to_date=arguments.to_date,
            )
        result = import_ibkr_flex_payloads(
            payloads,
            context=context,
            selection=IbkrFlexSelection(arguments.account_id, arguments.model),
            date_format=arguments.date_format,
            sampling=SamplingSpec(
                status=(
                    FrequencyStatus.DECLARED
                    if arguments.declared_frequency is not None
                    else FrequencyStatus.AMBIGUOUS
                ),
                declared_frequency=arguments.declared_frequency,
                periods_per_year=arguments.periods_per_year,
            ),
        )
    except InputValidationError as error:
        _print_input_validation_error(error)
        return 2
    except IbkrFlexError as error:
        print(
            json.dumps(
                {"error": "ibkr_flex_service_failed", "message": str(error)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 4
    except ValueError as error:
        parser.error(str(error))

    try:
        output.write_text(result.canonical_csv, encoding="utf-8", newline="\n")
        manifest_output.write_text(
            result.manifest_json,
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        print(f"Could not write IBKR Flex import: {error}", file=sys.stderr)
        return 3
    print(
        json.dumps(
            {
                "canonical_csv": str(output),
                "import_manifest": str(manifest_output),
                "import_sha256": result.import_sha256,
                "period_count": len(result.normalized.periods),
            },
            sort_keys=True,
        )
    )
    return 0


def _main_family(argv: Sequence[str]) -> int:
    parser = build_family_parser()
    arguments = parser.parse_args(argv)
    run_manifest_spec = _run_manifest_spec_from_arguments(parser, arguments)
    dsr_arguments = (
        arguments.dsr_method,
        arguments.dsr_trial_count_policy,
        arguments.dsr_annual_risk_free_rate,
        arguments.dsr_confidence_level,
    )
    if any(value is not None for value in dsr_arguments) and any(
        value is None for value in dsr_arguments
    ):
        parser.error(
            "--dsr-method, --dsr-trial-count-policy, "
            "--dsr-annual-risk-free-rate, and --dsr-confidence-level "
            "must be supplied together"
        )
    effective_arguments = (
        arguments.dsr_effective_independent_trials,
        arguments.dsr_effective_trial_count_methodology,
    )
    if (effective_arguments[0] is None) != (effective_arguments[1] is None):
        parser.error(
            "--dsr-effective-independent-trials and "
            "--dsr-effective-trial-count-methodology must be supplied "
            "together"
        )
    if effective_arguments[0] is not None and arguments.dsr_method is None:
        parser.error(
            "effective DSR trial-count arguments require the complete DSR configuration"
        )
    cscv_arguments = (
        arguments.cscv_method,
        arguments.cscv_performance_metric,
        arguments.cscv_selection_metric_name,
        arguments.cscv_partitions,
        arguments.cscv_annual_risk_free_rate,
        arguments.cscv_maximum_combinations,
        arguments.cscv_rank_tie_method,
        arguments.cscv_winner_tie_policy,
        arguments.cscv_maximum_acceptable_pbo,
    )
    if any(value is not None for value in cscv_arguments) and not all(
        value is not None for value in cscv_arguments
    ):
        parser.error("all --cscv-* configuration arguments must be supplied together")
    parameter_arguments = (
        arguments.parameter_robustness_metric,
        arguments.parameter_selection_metric_name,
        arguments.parameter_annual_risk_free_rate,
        arguments.parameter_distance_metric,
        arguments.parameter_scale,
        arguments.parameter_maximum_distance,
        arguments.parameter_minimum_neighbors,
        arguments.parameter_maximum_score_difference,
        arguments.parameter_minimum_acceptable_neighbor_fraction,
    )
    if any(value is not None for value in parameter_arguments) and not all(
        value is not None for value in parameter_arguments
    ):
        parser.error(
            "all parameter-robustness configuration arguments must be supplied together"
        )
    temporal_arguments = (
        arguments.temporal_robustness_metric,
        arguments.temporal_selection_metric_name,
        arguments.temporal_annual_risk_free_rate,
        arguments.temporal_windows,
        arguments.temporal_rank_tie_method,
        arguments.temporal_winner_tie_policy,
        arguments.temporal_minimum_acceptable_top_half_fraction,
        arguments.temporal_maximum_acceptable_below_zero_fraction,
    )
    if any(value is not None for value in temporal_arguments) and not all(
        value is not None for value in temporal_arguments
    ):
        parser.error(
            "all temporal-robustness configuration arguments must be supplied together"
        )
    data_snooping_arguments = (
        arguments.data_snooping_replications,
        arguments.data_snooping_mean_block_length,
        arguments.data_snooping_seed,
        arguments.data_snooping_significance_level,
    )
    if any(value is not None for value in data_snooping_arguments) and not all(
        value is not None for value in data_snooping_arguments
    ):
        parser.error("all --data-snooping-* arguments must be supplied together")
    if (
        arguments.data_snooping_replications is not None
        and arguments.benchmark_csv is None
    ):
        parser.error("data-snooping tests require --benchmark-csv")
    try:
        normalized = read_experiment_family_files(
            arguments.manifest_json,
            arguments.trials_csv,
            arguments.returns_csv,
            splits_path=arguments.splits_csv,
            benchmark_path=arguments.benchmark_csv,
        )
        input_artifacts = (
            ()
            if run_manifest_spec is None
            else tuple(
                hash_input_file(role, path)
                for role, path in (
                    ("family_manifest", arguments.manifest_json),
                    ("family_trials", arguments.trials_csv),
                    ("family_returns", arguments.returns_csv),
                    ("family_splits", arguments.splits_csv),
                    ("shared_benchmark", arguments.benchmark_csv),
                )
                if path is not None
            )
        )
        result = audit_experiment_family(
            normalized.family,
            input_issues=normalized.issues,
            dsr_spec=(
                None
                if arguments.dsr_method is None
                else DeflatedSharpeRatioSpec(
                    method=DeflatedSharpeRatioMethod(arguments.dsr_method),
                    trial_count_policy=DSRTrialCountPolicy(
                        arguments.dsr_trial_count_policy
                    ),
                    annual_risk_free_rate=(arguments.dsr_annual_risk_free_rate),
                    required_confidence_level=(arguments.dsr_confidence_level),
                    effective_independent_trial_count=(
                        arguments.dsr_effective_independent_trials
                    ),
                    effective_trial_count_methodology=(
                        arguments.dsr_effective_trial_count_methodology
                    ),
                )
            ),
            cscv_spec=(
                None
                if arguments.cscv_method is None
                else CSCVSpec(
                    method=CSCVMethod(arguments.cscv_method),
                    performance_metric=CSCVPerformanceMetric(
                        arguments.cscv_performance_metric
                    ),
                    selection_metric_name=arguments.cscv_selection_metric_name,
                    partition_count=arguments.cscv_partitions,
                    annual_risk_free_rate=arguments.cscv_annual_risk_free_rate,
                    maximum_combinations=arguments.cscv_maximum_combinations,
                    rank_tie_method=CSCVRankTieMethod(arguments.cscv_rank_tie_method),
                    winner_tie_policy=CSCVWinnerTiePolicy(
                        arguments.cscv_winner_tie_policy
                    ),
                    maximum_acceptable_pbo=(arguments.cscv_maximum_acceptable_pbo),
                )
            ),
            parameter_robustness_spec=(
                None
                if arguments.parameter_robustness_metric is None
                else ParameterRobustnessSpec(
                    performance_metric=RobustnessPerformanceMetric(
                        arguments.parameter_robustness_metric
                    ),
                    selection_metric_name=(arguments.parameter_selection_metric_name),
                    annual_risk_free_rate=(arguments.parameter_annual_risk_free_rate),
                    distance_metric=ParameterDistanceMetric(
                        arguments.parameter_distance_metric
                    ),
                    parameter_scales=tuple(arguments.parameter_scale),
                    maximum_distance=arguments.parameter_maximum_distance,
                    minimum_neighbor_count=arguments.parameter_minimum_neighbors,
                    maximum_acceptable_score_difference=(
                        arguments.parameter_maximum_score_difference
                    ),
                    minimum_acceptable_neighbor_fraction=(
                        arguments.parameter_minimum_acceptable_neighbor_fraction
                    ),
                )
            ),
            temporal_robustness_spec=(
                None
                if arguments.temporal_robustness_metric is None
                else TemporalRobustnessSpec(
                    performance_metric=RobustnessPerformanceMetric(
                        arguments.temporal_robustness_metric
                    ),
                    selection_metric_name=(arguments.temporal_selection_metric_name),
                    annual_risk_free_rate=(arguments.temporal_annual_risk_free_rate),
                    window_count=arguments.temporal_windows,
                    rank_tie_method=RobustnessRankTieMethod(
                        arguments.temporal_rank_tie_method
                    ),
                    winner_tie_policy=RobustnessWinnerTiePolicy(
                        arguments.temporal_winner_tie_policy
                    ),
                    minimum_acceptable_top_half_fraction=(
                        arguments.temporal_minimum_acceptable_top_half_fraction
                    ),
                    maximum_acceptable_below_zero_fraction=(
                        arguments.temporal_maximum_acceptable_below_zero_fraction
                    ),
                )
            ),
            data_snooping_spec=(
                None
                if arguments.data_snooping_replications is None
                else DataSnoopingSpec(
                    replications=arguments.data_snooping_replications,
                    mean_block_length=arguments.data_snooping_mean_block_length,
                    random_seed=arguments.data_snooping_seed,
                    significance_level=arguments.data_snooping_significance_level,
                )
            ),
            run_manifest_spec=run_manifest_spec,
            input_artifacts=input_artifacts,
        )
    except InputValidationError as error:
        _print_input_validation_error(error)
        return 2
    except ValueError as error:
        parser.error(str(error))

    return _emit_report(
        result,
        report_format=arguments.format,
        output=arguments.output,
    )


def _main_single(argv: Sequence[str]) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    run_manifest_spec = _run_manifest_spec_from_arguments(parser, arguments)

    if (
        arguments.required_psr_confidence_level is not None
        and arguments.benchmark_annualized_sharpe_ratio is None
    ):
        parser.error(
            "--required-psr-confidence-level requires "
            "--benchmark-annualized-sharpe-ratio"
        )

    if (arguments.serial_max_lag is None) != (
        arguments.serial_significance_level is None
    ):
        parser.error(
            "--serial-max-lag and --serial-significance-level must be supplied together"
        )

    if (arguments.hac_max_lag is None) != (arguments.hac_kernel is None):
        parser.error("--hac-max-lag and --hac-kernel must be supplied together")

    if (arguments.minimum_acceptable_period_return is None) != (
        arguments.tail_confidence_level is None
    ):
        parser.error(
            "--minimum-acceptable-period-return and --tail-confidence-level must be supplied together"
        )
    if (arguments.benchmark_alpha_hac_max_lag is None) != (
        arguments.benchmark_alpha_confidence_level is None
    ):
        parser.error(
            "--benchmark-alpha-hac-max-lag and --benchmark-alpha-confidence-level must be supplied together"
        )
    if (
        arguments.benchmark_alpha_hac_max_lag is not None
        and arguments.benchmark_csv is None
    ):
        parser.error(
            "benchmark alpha inference requires --benchmark-csv and --benchmark-id"
        )

    bootstrap_arguments = (
        arguments.bootstrap_method,
        arguments.bootstrap_interval_method,
        arguments.bootstrap_replications,
        arguments.bootstrap_confidence_level,
        arguments.bootstrap_block_length,
        arguments.bootstrap_seed,
    )
    if any(value is not None for value in bootstrap_arguments) and not all(
        value is not None for value in bootstrap_arguments
    ):
        parser.error(
            "--bootstrap-method, --bootstrap-interval-method, "
            "--bootstrap-replications, --bootstrap-confidence-level, "
            "--bootstrap-block-length, and --bootstrap-seed must be "
            "supplied together"
        )

    if (arguments.observation_calendar is None) != (
        arguments.calendar_timezone is None
    ):
        parser.error(
            "--observation-calendar and --calendar-timezone must be supplied together"
        )
    if (
        arguments.calendar_sessions_csv is not None
        and arguments.observation_calendar is None
    ):
        parser.error(
            "--calendar-sessions-csv requires --observation-calendar "
            "and --calendar-timezone"
        )

    if (arguments.benchmark_csv is None) != (arguments.benchmark_id is None):
        parser.error("--benchmark-csv and --benchmark-id must be supplied together")
    if (arguments.benchmark_observation_calendar is None) != (
        arguments.benchmark_calendar_timezone is None
    ):
        parser.error(
            "--benchmark-observation-calendar and "
            "--benchmark-calendar-timezone must be supplied together"
        )
    if (
        arguments.benchmark_calendar_sessions_csv is not None
        and arguments.benchmark_observation_calendar is None
    ):
        parser.error(
            "--benchmark-calendar-sessions-csv requires the benchmark "
            "calendar name and timezone"
        )
    benchmark_optional_values = (
        arguments.benchmark_timestamp_timezone,
        arguments.benchmark_observation_calendar,
        arguments.benchmark_calendar_sessions_csv,
        arguments.benchmark_transaction_costs_included,
        arguments.benchmark_fees_included,
        arguments.benchmark_leverage_policy,
        arguments.benchmark_currency,
        arguments.benchmark_price_adjustment_policy,
        arguments.benchmark_data_source,
        arguments.benchmark_data_vintage,
        arguments.benchmark_stale_price_policy,
        arguments.benchmark_delisting_return_policy,
        arguments.benchmark_survivorship_bias_controlled,
        arguments.benchmark_lookahead_bias_controlled,
        arguments.benchmark_signal_timing,
        arguments.benchmark_execution_timing,
    )
    if arguments.benchmark_csv is None and any(
        value is not None for value in benchmark_optional_values
    ):
        parser.error(
            "benchmark-specific calendar or metadata arguments require "
            "--benchmark-csv and --benchmark-id"
        )

    try:
        observation_calendar = _calendar_spec_from_arguments(arguments)
        return_construction = _return_construction_from_arguments(arguments)
        normalized = read_return_series_csv(
            arguments.input_csv,
            timestamp_column=arguments.timestamp_column,
            return_column=arguments.return_column,
            convention=ReturnConvention(arguments.return_convention),
            sampling=SamplingSpec(
                status=(
                    FrequencyStatus.DECLARED
                    if arguments.declared_frequency is not None
                    else FrequencyStatus.AMBIGUOUS
                ),
                declared_frequency=arguments.declared_frequency,
                periods_per_year=arguments.periods_per_year,
                timezone=arguments.timestamp_timezone,
            ),
        )
        benchmark = None
        benchmark_issues: tuple[ValidationIssue, ...] = ()
        if arguments.benchmark_csv is not None:
            benchmark_calendar = _calendar_spec_from_arguments(
                arguments,
                prefix="benchmark",
            )
            benchmark_construction = _return_construction_from_arguments(
                arguments,
                prefix="benchmark",
            )
            normalized_benchmark = read_return_series_csv(
                arguments.benchmark_csv,
                timestamp_column=arguments.benchmark_timestamp_column,
                return_column=arguments.benchmark_return_column,
                convention=ReturnConvention(arguments.benchmark_return_convention),
                sampling=SamplingSpec(
                    status=(
                        FrequencyStatus.DECLARED
                        if arguments.declared_frequency is not None
                        else FrequencyStatus.AMBIGUOUS
                    ),
                    declared_frequency=arguments.declared_frequency,
                    periods_per_year=arguments.periods_per_year,
                    timezone=arguments.benchmark_timestamp_timezone,
                ),
                name=arguments.benchmark_id,
            )
            benchmark_issues = normalized_benchmark.issues
            benchmark = BenchmarkRun(
                benchmark_id=arguments.benchmark_id,
                returns=normalized_benchmark.series,
                observation_calendar=benchmark_calendar,
                return_construction=benchmark_construction,
            )
        auxiliary_sampling = SamplingSpec(
            status=(
                FrequencyStatus.DECLARED
                if arguments.declared_frequency is not None
                else FrequencyStatus.AMBIGUOUS
            ),
            declared_frequency=arguments.declared_frequency,
            periods_per_year=arguments.periods_per_year,
            timezone=arguments.timestamp_timezone,
        )
        risk_free = None
        risk_free_issues: tuple[ValidationIssue, ...] = ()
        if arguments.risk_free_csv is not None:
            normalized_risk_free = read_return_series_csv(
                arguments.risk_free_csv,
                timestamp_column=arguments.risk_free_timestamp_column,
                return_column=arguments.risk_free_return_column,
                convention=ReturnConvention(arguments.risk_free_return_convention),
                sampling=auxiliary_sampling,
                name="risk_free",
            )
            risk_free = normalized_risk_free.series
            risk_free_issues = normalized_risk_free.issues
        gross_returns = None
        gross_issues: tuple[ValidationIssue, ...] = ()
        if arguments.gross_returns_csv is not None:
            normalized_gross = read_return_series_csv(
                arguments.gross_returns_csv,
                timestamp_column=arguments.gross_timestamp_column,
                return_column=arguments.gross_return_column,
                convention=ReturnConvention(arguments.gross_return_convention),
                sampling=auxiliary_sampling,
                name="gross_strategy",
            )
            gross_returns = normalized_gross.series
            gross_issues = normalized_gross.issues
        regimes = None
        regime_issues: tuple[ValidationIssue, ...] = ()
        if arguments.regimes_csv is not None:
            normalized_regimes = read_regime_series_csv(
                arguments.regimes_csv,
                timestamp_column=arguments.regime_timestamp_column,
                regime_column=arguments.regime_column,
            )
            regimes = normalized_regimes.series
            regime_issues = normalized_regimes.issues
        input_artifacts = (
            ()
            if run_manifest_spec is None
            else tuple(
                hash_input_file(role, path)
                for role, path in (
                    ("strategy_returns", arguments.input_csv),
                    ("strategy_calendar_sessions", arguments.calendar_sessions_csv),
                    ("benchmark_returns", arguments.benchmark_csv),
                    ("risk_free_returns", arguments.risk_free_csv),
                    ("gross_strategy_returns", arguments.gross_returns_csv),
                    ("declared_regimes", arguments.regimes_csv),
                    (
                        "benchmark_calendar_sessions",
                        arguments.benchmark_calendar_sessions_csv,
                    ),
                )
                if path is not None
            )
        )
        result = audit_single_run(
            StrategyRun(
                run_id=arguments.run_id,
                returns=normalized.series,
                observation_calendar=observation_calendar,
                return_construction=return_construction,
                benchmark=benchmark,
                risk_free_returns=risk_free,
                gross_returns=gross_returns,
                regimes=regimes,
            ),
            input_issues=(
                normalized.issues
                + benchmark_issues
                + risk_free_issues
                + gross_issues
                + regime_issues
            ),
            sharpe_spec=(
                None
                if arguments.annual_risk_free_rate is None
                else SharpeRatioSpec(
                    annual_risk_free_rate=(arguments.annual_risk_free_rate)
                )
            ),
            psr_spec=(
                None
                if (arguments.benchmark_annualized_sharpe_ratio is None)
                else ProbabilisticSharpeRatioSpec(
                    benchmark_annualized_sharpe_ratio=(
                        arguments.benchmark_annualized_sharpe_ratio
                    ),
                    required_psr_confidence_level=(
                        arguments.required_psr_confidence_level
                    ),
                )
            ),
            serial_dependence_spec=(
                None
                if arguments.serial_max_lag is None
                else SerialDependenceSpec(
                    maximum_lag=arguments.serial_max_lag,
                    significance_level=(arguments.serial_significance_level),
                )
            ),
            serial_adjustment_spec=(
                None
                if arguments.hac_max_lag is None
                else SerialAdjustmentSpec(
                    maximum_lag=arguments.hac_max_lag,
                    kernel=HACKernel(arguments.hac_kernel),
                )
            ),
            bootstrap_spec=(
                None
                if arguments.bootstrap_method is None
                else BootstrapSpec(
                    method=BootstrapMethod(arguments.bootstrap_method),
                    interval_method=BootstrapIntervalMethod(
                        arguments.bootstrap_interval_method
                    ),
                    replications=arguments.bootstrap_replications,
                    confidence_level=(arguments.bootstrap_confidence_level),
                    block_length=arguments.bootstrap_block_length,
                    random_seed=arguments.bootstrap_seed,
                )
            ),
            advanced_risk_spec=(
                None
                if arguments.minimum_acceptable_period_return is None
                else AdvancedRiskSpec(
                    minimum_acceptable_period_return=(
                        arguments.minimum_acceptable_period_return
                    ),
                    tail_confidence_level=arguments.tail_confidence_level,
                )
            ),
            benchmark_inference_spec=(
                None
                if arguments.benchmark_alpha_hac_max_lag is None
                else BenchmarkInferenceSpec(
                    maximum_lag=arguments.benchmark_alpha_hac_max_lag,
                    confidence_level=arguments.benchmark_alpha_confidence_level,
                )
            ),
            run_manifest_spec=run_manifest_spec,
            input_artifacts=input_artifacts,
        )
    except InputValidationError as error:
        _print_input_validation_error(error)
        return 2
    except ValueError as error:
        parser.error(str(error))

    return _emit_report(
        result,
        report_format=arguments.format,
        output=arguments.output,
    )


def _emit_report(
    result: SingleRunAuditResult | ExperimentFamilyAuditResult,
    *,
    report_format: str,
    output: Path | None,
) -> int:
    try:
        report = (
            render_json_report(result)
            if report_format == "json"
            else render_markdown_report(result)
        )
    except ValueError as error:
        # json.dumps uses allow_nan=False, so a non-finite value anywhere in a
        # fully computed report aborted serialisation with a bare traceback,
        # bypassing the machine-readable stderr contract the rest of the CLI
        # guarantees. Report it in the same envelope shape instead.
        print(
            json.dumps(
                {
                    "error": "report_serialization_failed",
                    "message": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 4
    if output is None:
        print(report, end="")
        return 0

    try:
        output.write_text(
            report,
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        print(
            f"Could not write report: {error}",
            file=sys.stderr,
        )
        return 3

    return 0


def _emit_implementation_risk_report(
    result: ImplementationRiskAuditResult,
    *,
    report_format: str,
    output: Path | None,
) -> int:
    report = (
        render_implementation_risk_json(result)
        if report_format == "json"
        else render_implementation_risk_markdown(result)
    )
    if output is None:
        print(report, end="")
        return 0
    try:
        _write_text_atomic(output, report)
    except OSError as error:
        print(f"Could not write report: {error}", file=sys.stderr)
        return 3
    return 0


def _write_text_atomic(output: Path, report: str) -> None:
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(report)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _print_input_validation_error(
    error: InputValidationError,
) -> None:
    payload = {
        "error": "input_validation_failed",
        "issues": [validation_issue_to_dict(issue) for issue in error.issues],
    }
    print(
        json.dumps(payload, sort_keys=True),
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
