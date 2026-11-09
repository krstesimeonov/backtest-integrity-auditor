"""Framework-neutral controller used by the optional Streamlit interface.

The controller materializes uploaded bytes only long enough to pass them through
the canonical ingestion and application services.  It deliberately contains no
statistical calculations and does not invoke the command-line interface.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from backtest_auditor import PACKAGE_VERSION, REPORT_SCHEMA_VERSION
from backtest_auditor.application.audit_repository import (
    AuditSnapshot,
    NormalizedObservation,
    NormalizedSeriesSnapshot,
)

from backtest_auditor.application.experiment_family_audit import (
    ExperimentFamilyAuditResult,
    audit_experiment_family,
)
from backtest_auditor.application.ibkr_flex_import import (
    IbkrFlexImportContext,
    import_ibkr_flex_payloads,
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
    ProbabilisticSharpeRatioSpec,
    SerialAdjustmentSpec,
    SerialDependenceSpec,
    SharpeRatioSpec,
    TemporalRobustnessSpec,
)
from backtest_auditor.domain.enums import FrequencyStatus, ReturnConvention
from backtest_auditor.domain.issues import ValidationIssue
from backtest_auditor.domain.metadata import (
    ObservationCalendarSpec,
    ReturnConstructionSpec,
)
from backtest_auditor.domain.reproducibility import AuditRunSpec, InputArtifactHash
from backtest_auditor.domain.runs import BenchmarkRun, StrategyRun
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.ingestion.calendar_sessions import (
    read_calendar_session_dates_csv,
)
from backtest_auditor.ingestion.csv_returns import read_return_series_csv
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)
from backtest_auditor.ingestion.file_hashing import hash_input_file
from backtest_auditor.ingestion.ibkr_flex import (
    IbkrFlexPayload,
    IbkrFlexSelection,
)
from backtest_auditor.ingestion.regimes import read_regime_series_csv
from backtest_auditor.integrations.ibkr_flex import (
    FlexWebServiceClient,
    IbkrFlexCredentials,
    IbkrFlexRequest,
)
from backtest_auditor.reporting.json_report import render_json_report
from backtest_auditor.reporting.markdown_report import render_markdown_report
from backtest_auditor.implementation_risk import (
    IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION,
    MAX_IMPLEMENTATION_RISK_CANDIDATES,
    MAX_POLICY_JSON_BYTES,
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditService,
    comparison_policy_from_json,
    divergence_policy_from_json,
    implementation_risk_audit_to_dict,
    normalization_plan_from_json,
    parse_policy_json_bytes,
    render_implementation_risk_json,
    render_implementation_risk_markdown,
    risk_policy_from_json,
)


_MAX_IMPLEMENTATION_RISK_BUNDLE_UPLOAD_BYTES = 512_000_000


@dataclass(frozen=True, slots=True)
class UploadedInput:
    """One browser upload with a safe display name and immutable raw bytes."""

    name: str
    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise ValueError("uploaded input name must be a string.")
        safe_name = self.name.strip().replace("\\", "/").rsplit("/", 1)[-1]
        if safe_name in {"", ".", ".."}:
            raise ValueError("uploaded input name must identify a file.")
        if any(ord(character) < 32 or ord(character) == 127 for character in safe_name):
            raise ValueError("uploaded input name must not contain control characters.")
        if len(safe_name.encode("utf-8")) > 255:
            raise ValueError("uploaded input name must not exceed 255 UTF-8 bytes.")
        if not isinstance(self.content, bytes):
            raise ValueError("uploaded input content must be bytes.")
        object.__setattr__(self, "name", safe_name)


@dataclass(frozen=True, slots=True)
class CalendarInput:
    calendar_name: str
    timezone: str
    sessions_file: UploadedInput | None = None
    session_column: str = "session"

    def __post_init__(self) -> None:
        if not self.session_column.strip():
            raise ValueError("calendar session column must not be empty.")


@dataclass(frozen=True, slots=True)
class BenchmarkInput:
    returns_file: UploadedInput
    benchmark_id: str
    timestamp_column: str = "timestamp"
    return_column: str = "return"
    return_convention: ReturnConvention = ReturnConvention.SIMPLE
    timestamp_timezone: str | None = None
    observation_calendar: CalendarInput | None = None
    return_construction: ReturnConstructionSpec | None = None


@dataclass(frozen=True, slots=True)
class SingleRunRequest:
    returns_file: UploadedInput
    run_id: str
    timestamp_column: str = "timestamp"
    return_column: str = "return"
    return_convention: ReturnConvention = ReturnConvention.SIMPLE
    declared_frequency: str | None = None
    periods_per_year: int | None = None
    timestamp_timezone: str | None = None
    observation_calendar: CalendarInput | None = None
    return_construction: ReturnConstructionSpec | None = None
    benchmark: BenchmarkInput | None = None
    risk_free_file: UploadedInput | None = None
    risk_free_timestamp_column: str = "timestamp"
    risk_free_return_column: str = "return"
    risk_free_return_convention: ReturnConvention = ReturnConvention.SIMPLE
    gross_returns_file: UploadedInput | None = None
    gross_timestamp_column: str = "timestamp"
    gross_return_column: str = "return"
    gross_return_convention: ReturnConvention = ReturnConvention.SIMPLE
    regimes_file: UploadedInput | None = None
    regime_timestamp_column: str = "timestamp"
    regime_column: str = "regime"
    sharpe_spec: SharpeRatioSpec | None = None
    psr_spec: ProbabilisticSharpeRatioSpec | None = None
    serial_dependence_spec: SerialDependenceSpec | None = None
    serial_adjustment_spec: SerialAdjustmentSpec | None = None
    bootstrap_spec: BootstrapSpec | None = None
    advanced_risk_spec: AdvancedRiskSpec | None = None
    benchmark_inference_spec: BenchmarkInferenceSpec | None = None
    run_manifest_spec: AuditRunSpec | None = None


@dataclass(frozen=True, slots=True)
class ExperimentFamilyRequest:
    manifest_file: UploadedInput
    trials_file: UploadedInput
    returns_file: UploadedInput
    splits_file: UploadedInput | None = None
    benchmark_file: UploadedInput | None = None
    dsr_spec: DeflatedSharpeRatioSpec | None = None
    cscv_spec: CSCVSpec | None = None
    parameter_robustness_spec: ParameterRobustnessSpec | None = None
    temporal_robustness_spec: TemporalRobustnessSpec | None = None
    data_snooping_spec: DataSnoopingSpec | None = None
    run_manifest_spec: AuditRunSpec | None = None


@dataclass(frozen=True, slots=True)
class IbkrFlexImportRequest:
    source_mode: str
    statement_files: tuple[UploadedInput, ...] = ()
    token: str | None = field(default=None, repr=False)
    query_id: str | None = field(default=None, repr=False)
    requested_from_date: date | None = None
    requested_to_date: date | None = None
    account_id: str | None = field(default=None, repr=False)
    model: str | None = None
    date_format: str = "yyyyMMdd"
    declared_frequency: str | None = None
    periods_per_year: int | None = None

    def __post_init__(self) -> None:
        if self.source_mode not in {"files", "api"}:
            raise ValueError("IBKR Flex source_mode must be files or api.")
        if self.source_mode == "files":
            if not self.statement_files:
                raise ValueError("At least one IBKR Flex statement file is required.")
            if self.token is not None or self.query_id is not None:
                raise ValueError("File imports must not contain API credentials.")
        elif not self.token or not self.query_id:
            raise ValueError("API imports require a Flex token and query ID.")


@dataclass(frozen=True, slots=True)
class IbkrFlexImportPresentation:
    canonical_csv: str
    manifest_json: str
    import_sha256: str
    period_count: int
    first_period_start: str
    last_period_end: str
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditPresentation:
    audit_type: str
    subject_id: str
    payload: dict[str, object]
    json_report: str
    markdown_report: str
    normalized_series: tuple[NormalizedSeriesSnapshot, ...] = ()
    report_schema_version: str = REPORT_SCHEMA_VERSION
    package_version: str = PACKAGE_VERSION


@dataclass(frozen=True, slots=True)
class ImplementationRiskRequest:
    reference_bundle: UploadedInput
    candidate_bundles: tuple[UploadedInput, ...]
    normalization_plan_file: UploadedInput
    comparison_policy_file: UploadedInput
    measurement_policy_file: UploadedInput
    assessment_policy_file: UploadedInput
    run_manifest_spec: AuditRunSpec | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference_bundle, UploadedInput):
            raise ValueError("reference_bundle must be an uploaded file.")
        if not self.candidate_bundles:
            raise ValueError("At least one candidate bundle is required.")
        if any(not isinstance(item, UploadedInput) for item in self.candidate_bundles):
            raise ValueError("candidate_bundles must contain uploaded files.")
        if len(self.candidate_bundles) > MAX_IMPLEMENTATION_RISK_CANDIDATES:
            raise ValueError(
                "candidate_bundles exceed the maximum of "
                f"{MAX_IMPLEMENTATION_RISK_CANDIDATES}."
            )
        bundle_uploads = (self.reference_bundle, *self.candidate_bundles)
        if any(
            len(item.content) > _MAX_IMPLEMENTATION_RISK_BUNDLE_UPLOAD_BYTES
            for item in bundle_uploads
        ):
            raise ValueError(
                "implementation-risk bundle upload exceeds the safety limit."
            )
        policy_uploads = (
            self.normalization_plan_file,
            self.comparison_policy_file,
            self.measurement_policy_file,
            self.assessment_policy_file,
        )
        if any(not isinstance(item, UploadedInput) for item in policy_uploads):
            raise ValueError("implementation-risk policies must be uploaded files.")
        if any(len(item.content) > MAX_POLICY_JSON_BYTES for item in policy_uploads):
            raise ValueError(
                "implementation-risk policy upload exceeds the safety limit."
            )


@dataclass(frozen=True, slots=True)
class ImplementationRiskPresentation:
    reconciliation_id: str
    candidate_count: int
    payload: dict[str, object]
    json_report: str
    markdown_report: str
    report_schema_version: str = IMPLEMENTATION_RISK_REPORT_SCHEMA_VERSION
    package_version: str = PACKAGE_VERSION


def run_single_audit(request: SingleRunRequest) -> AuditPresentation:
    """Execute one uploaded Single-Run audit through the V1 application API."""

    with TemporaryDirectory(prefix="backtest-auditor-ui-") as temporary:
        root = Path(temporary)
        returns_path = _materialize(root, "strategy_returns", request.returns_file)
        strategy_calendar = _calendar_spec(
            root,
            "strategy_calendar_sessions",
            request.observation_calendar,
        )
        sampling = _sampling(
            request.declared_frequency,
            request.periods_per_year,
            request.timestamp_timezone,
        )
        normalized = read_return_series_csv(
            returns_path,
            timestamp_column=request.timestamp_column,
            return_column=request.return_column,
            convention=ReturnConvention(request.return_convention),
            sampling=sampling,
        )

        benchmark = None
        benchmark_issues: tuple[ValidationIssue, ...] = ()
        if request.benchmark is not None:
            benchmark_request = request.benchmark
            benchmark_path = _materialize(
                root,
                "benchmark_returns",
                benchmark_request.returns_file,
            )
            benchmark_calendar = _calendar_spec(
                root,
                "benchmark_calendar_sessions",
                benchmark_request.observation_calendar,
            )
            normalized_benchmark = read_return_series_csv(
                benchmark_path,
                timestamp_column=benchmark_request.timestamp_column,
                return_column=benchmark_request.return_column,
                convention=ReturnConvention(benchmark_request.return_convention),
                sampling=_sampling(
                    request.declared_frequency,
                    request.periods_per_year,
                    benchmark_request.timestamp_timezone,
                ),
                name=benchmark_request.benchmark_id,
            )
            benchmark_issues = normalized_benchmark.issues
            benchmark = BenchmarkRun(
                benchmark_id=benchmark_request.benchmark_id,
                returns=normalized_benchmark.series,
                observation_calendar=benchmark_calendar,
                return_construction=benchmark_request.return_construction,
            )

        risk_free = None
        risk_free_issues: tuple[ValidationIssue, ...] = ()
        if request.risk_free_file is not None:
            risk_free_path = _materialize(
                root, "risk_free_returns", request.risk_free_file
            )
            normalized_risk_free = read_return_series_csv(
                risk_free_path,
                timestamp_column=request.risk_free_timestamp_column,
                return_column=request.risk_free_return_column,
                convention=request.risk_free_return_convention,
                sampling=sampling,
                name="risk_free",
            )
            risk_free = normalized_risk_free.series
            risk_free_issues = normalized_risk_free.issues
        gross_returns = None
        gross_issues: tuple[ValidationIssue, ...] = ()
        if request.gross_returns_file is not None:
            gross_path = _materialize(
                root, "gross_strategy_returns", request.gross_returns_file
            )
            normalized_gross = read_return_series_csv(
                gross_path,
                timestamp_column=request.gross_timestamp_column,
                return_column=request.gross_return_column,
                convention=request.gross_return_convention,
                sampling=sampling,
                name="gross_strategy",
            )
            gross_returns = normalized_gross.series
            gross_issues = normalized_gross.issues
        regimes = None
        regime_issues: tuple[ValidationIssue, ...] = ()
        if request.regimes_file is not None:
            regime_path = _materialize(root, "declared_regimes", request.regimes_file)
            normalized_regimes = read_regime_series_csv(
                regime_path,
                timestamp_column=request.regime_timestamp_column,
                regime_column=request.regime_column,
            )
            regimes = normalized_regimes.series
            regime_issues = normalized_regimes.issues

        artifacts: tuple[InputArtifactHash, ...] = ()
        if request.run_manifest_spec is not None:
            artifacts = tuple(
                hash_input_file(role, path)
                for role, path in (
                    ("strategy_returns", returns_path),
                    (
                        "strategy_calendar_sessions",
                        _materialized_calendar_path(
                            root,
                            "strategy_calendar_sessions",
                            request.observation_calendar,
                        ),
                    ),
                    (
                        "benchmark_returns",
                        _materialized_path(
                            root, "benchmark_returns", request.benchmark
                        ),
                    ),
                    (
                        "benchmark_calendar_sessions",
                        _materialized_benchmark_calendar_path(root, request.benchmark),
                    ),
                    (
                        "risk_free_returns",
                        _materialized_upload_path(
                            root, "risk_free_returns", request.risk_free_file
                        ),
                    ),
                    (
                        "gross_strategy_returns",
                        _materialized_upload_path(
                            root, "gross_strategy_returns", request.gross_returns_file
                        ),
                    ),
                    (
                        "declared_regimes",
                        _materialized_upload_path(
                            root, "declared_regimes", request.regimes_file
                        ),
                    ),
                )
                if path is not None
            )

        result = audit_single_run(
            StrategyRun(
                run_id=request.run_id,
                returns=normalized.series,
                observation_calendar=strategy_calendar,
                return_construction=request.return_construction,
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
            sharpe_spec=request.sharpe_spec,
            psr_spec=request.psr_spec,
            serial_dependence_spec=request.serial_dependence_spec,
            serial_adjustment_spec=request.serial_adjustment_spec,
            bootstrap_spec=request.bootstrap_spec,
            advanced_risk_spec=request.advanced_risk_spec,
            benchmark_inference_spec=request.benchmark_inference_spec,
            run_manifest_spec=request.run_manifest_spec,
            input_artifacts=artifacts,
        )
    snapshots = [_series_snapshot("strategy", result.run_id, normalized.series)]
    if benchmark is not None:
        snapshots.append(
            _series_snapshot("benchmark", benchmark.benchmark_id, benchmark.returns)
        )
    if risk_free is not None:
        snapshots.append(_series_snapshot("risk_free", "risk_free", risk_free))
    if gross_returns is not None:
        snapshots.append(
            _series_snapshot("gross_strategy", result.run_id, gross_returns)
        )
    return _presentation(result, "single_run", result.run_id, tuple(snapshots))


def run_ibkr_flex_import(
    request: IbkrFlexImportRequest,
    *,
    client: FlexWebServiceClient | None = None,
) -> IbkrFlexImportPresentation:
    """Import exported files or one read-only API response through one adapter."""

    if request.source_mode == "files":
        payloads = tuple(
            IbkrFlexPayload(upload.name, upload.content)
            for upload in request.statement_files
        )
        context = IbkrFlexImportContext(source_mode="files")
    else:
        assert request.token is not None
        assert request.query_id is not None
        service = client or FlexWebServiceClient()
        body = service.fetch_statement(
            IbkrFlexCredentials(request.token, request.query_id),
            IbkrFlexRequest(
                request.requested_from_date,
                request.requested_to_date,
            ),
        )
        payloads = (IbkrFlexPayload("ibkr-flex-api-response", body),)
        context = IbkrFlexImportContext(
            source_mode="api",
            query_id=request.query_id,
            requested_from_date=request.requested_from_date,
            requested_to_date=request.requested_to_date,
        )
    result = import_ibkr_flex_payloads(
        payloads,
        context=context,
        selection=IbkrFlexSelection(request.account_id, request.model),
        date_format=request.date_format,
        sampling=_sampling(
            request.declared_frequency,
            request.periods_per_year,
            None,
        ),
    )
    periods = result.normalized.periods
    return IbkrFlexImportPresentation(
        canonical_csv=result.canonical_csv,
        manifest_json=result.manifest_json,
        import_sha256=result.import_sha256,
        period_count=len(periods),
        first_period_start=periods[0].from_date.isoformat(),
        last_period_end=periods[-1].to_date.isoformat(),
        warning_codes=tuple(
            issue.code for issue in result.normalized.normalized.issues
        ),
    )


def run_family_audit(request: ExperimentFamilyRequest) -> AuditPresentation:
    """Execute one uploaded Experiment-Family audit through the V1 API."""

    with TemporaryDirectory(prefix="backtest-auditor-ui-") as temporary:
        root = Path(temporary)
        paths = {
            "family_manifest": _materialize(
                root, "family_manifest", request.manifest_file
            ),
            "family_trials": _materialize(root, "family_trials", request.trials_file),
            "family_returns": _materialize(
                root, "family_returns", request.returns_file
            ),
        }
        if request.splits_file is not None:
            paths["family_splits"] = _materialize(
                root, "family_splits", request.splits_file
            )
        if request.benchmark_file is not None:
            paths["shared_benchmark"] = _materialize(
                root, "shared_benchmark", request.benchmark_file
            )
        normalized = read_experiment_family_files(
            paths["family_manifest"],
            paths["family_trials"],
            paths["family_returns"],
            splits_path=paths.get("family_splits"),
            benchmark_path=paths.get("shared_benchmark"),
        )
        artifacts: tuple[InputArtifactHash, ...] = ()
        if request.run_manifest_spec is not None:
            artifacts = tuple(
                hash_input_file(role, path) for role, path in paths.items()
            )
        result = audit_experiment_family(
            normalized.family,
            input_issues=normalized.issues,
            dsr_spec=request.dsr_spec,
            cscv_spec=request.cscv_spec,
            parameter_robustness_spec=request.parameter_robustness_spec,
            temporal_robustness_spec=request.temporal_robustness_spec,
            data_snooping_spec=request.data_snooping_spec,
            run_manifest_spec=request.run_manifest_spec,
            input_artifacts=artifacts,
        )
    family = normalized.family
    snapshots = tuple(
        _series_snapshot("trial", trial_id, family.returns.series_for(trial_id))
        for trial_id in family.returns.trial_ids
    )
    if family.benchmark_returns is not None:
        snapshots += (
            _series_snapshot(
                "benchmark",
                family.manifest.benchmark_id or "benchmark",
                family.benchmark_returns,
            ),
        )
    return _presentation(result, "experiment_family", result.family_id, snapshots)


def run_implementation_risk_audit(
    request: ImplementationRiskRequest,
) -> ImplementationRiskPresentation:
    """Execute uploaded canonical bundles through the complete V1.5 pipeline."""

    if not isinstance(request, ImplementationRiskRequest):
        raise ValueError("request must be an ImplementationRiskRequest.")
    with TemporaryDirectory(
        prefix="backtest-auditor-implementation-risk-ui-"
    ) as temporary:
        root = Path(temporary)
        reference_path = _materialize(
            root, "reference_bundle", request.reference_bundle
        )
        candidate_paths = tuple(
            _materialize(root, f"candidate_bundle_{index}", upload)
            for index, upload in enumerate(request.candidate_bundles)
        )
        adapter = CanonicalArtifactFileBundleAdapter()
        artifacts = tuple(
            adapter.read(path) for path in (reference_path, *candidate_paths)
        )
        result = ImplementationRiskAuditService(adapter).audit(
            artifacts,
            normalization_plan_from_json(
                parse_policy_json_bytes(request.normalization_plan_file.content)
            ),
            comparison_policy_from_json(
                parse_policy_json_bytes(request.comparison_policy_file.content)
            ),
            divergence_policy_from_json(
                parse_policy_json_bytes(request.measurement_policy_file.content)
            ),
            risk_policy_from_json(
                parse_policy_json_bytes(request.assessment_policy_file.content)
            ),
            run_manifest_spec=request.run_manifest_spec,
        )
    payload = implementation_risk_audit_to_dict(result)
    return ImplementationRiskPresentation(
        result.assessment.scope.reconciliation_id,
        len(result.assessment.scope.candidate_runs),
        payload,
        render_implementation_risk_json(result),
        render_implementation_risk_markdown(result),
    )


def _materialize(root: Path, role: str, upload: UploadedInput) -> Path:
    role_directory = root / role
    role_directory.mkdir()
    path = role_directory / upload.name
    path.write_bytes(upload.content)
    return path


def _calendar_spec(
    root: Path,
    role: str,
    calendar: CalendarInput | None,
) -> ObservationCalendarSpec | None:
    if calendar is None:
        return None
    dates = None
    if calendar.sessions_file is not None:
        path = _materialize(root, role, calendar.sessions_file)
        dates = read_calendar_session_dates_csv(
            path,
            session_column=calendar.session_column,
        )
    return ObservationCalendarSpec(
        calendar_name=calendar.calendar_name,
        timezone=calendar.timezone,
        expected_session_dates=dates,
    )


def _sampling(
    declared_frequency: str | None,
    periods_per_year: int | None,
    timezone: str | None,
) -> SamplingSpec:
    return SamplingSpec(
        status=(
            FrequencyStatus.DECLARED
            if declared_frequency is not None
            else FrequencyStatus.AMBIGUOUS
        ),
        declared_frequency=declared_frequency,
        periods_per_year=periods_per_year,
        timezone=timezone,
    )


def _materialized_calendar_path(
    root: Path,
    role: str,
    calendar: CalendarInput | None,
) -> Path | None:
    if calendar is None or calendar.sessions_file is None:
        return None
    return root / role / calendar.sessions_file.name


def _materialized_path(
    root: Path,
    role: str,
    benchmark: BenchmarkInput | None,
) -> Path | None:
    if benchmark is None:
        return None
    return root / role / benchmark.returns_file.name


def _materialized_benchmark_calendar_path(
    root: Path,
    benchmark: BenchmarkInput | None,
) -> Path | None:
    if benchmark is None:
        return None
    return _materialized_calendar_path(
        root,
        "benchmark_calendar_sessions",
        benchmark.observation_calendar,
    )


def _materialized_upload_path(
    root: Path,
    role: str,
    upload: UploadedInput | None,
) -> Path | None:
    if upload is None:
        return None
    return root / role / upload.name


def _presentation(
    result: SingleRunAuditResult | ExperimentFamilyAuditResult,
    audit_type: str,
    subject_id: str,
    normalized_series: tuple[NormalizedSeriesSnapshot, ...] = (),
) -> AuditPresentation:
    json_report = render_json_report(result)
    payload = json.loads(json_report)
    assert isinstance(payload, dict)
    return AuditPresentation(
        audit_type=audit_type,
        subject_id=subject_id,
        payload=payload,
        json_report=json_report,
        markdown_report=render_markdown_report(result),
        normalized_series=normalized_series,
    )


def presentation_to_snapshot(result: AuditPresentation) -> AuditSnapshot:
    manifest = result.payload.get("run_manifest")
    return AuditSnapshot(
        audit_type=result.audit_type,
        subject_id=result.subject_id,
        report_schema_version=result.report_schema_version,
        package_version=result.package_version,
        json_report=result.json_report,
        markdown_report=result.markdown_report,
        manifest_json=(
            None
            if manifest is None
            else json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        ),
        normalized_series=result.normalized_series,
    )


def _series_snapshot(
    role: str, series_id: str, values: ReturnSeries
) -> NormalizedSeriesSnapshot:
    sampling = values.sampling
    sampling_json = json.dumps(
        {
            "status": sampling.status.value,
            "declared_frequency": sampling.declared_frequency,
            "periods_per_year": sampling.periods_per_year,
            "timezone": sampling.timezone,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return NormalizedSeriesSnapshot(
        role=role,
        series_id=series_id,
        return_convention=values.convention.value,
        sampling_json=sampling_json,
        observations=tuple(
            NormalizedObservation(timestamp.isoformat(), float(value))
            for timestamp, value in zip(values.timestamps, values.values, strict=True)
        ),
    )
