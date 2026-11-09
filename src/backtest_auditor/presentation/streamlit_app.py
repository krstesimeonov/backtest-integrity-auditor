"""Streamlit presentation and optional history for the auditor."""

import json
import inspect
import os
from datetime import datetime
from typing import Any

import streamlit as st

from backtest_auditor import PACKAGE_VERSION, REPORT_SCHEMA_VERSION
from backtest_auditor.domain.assumptions import (
    AdvancedRiskSpec,
    BenchmarkInferenceSpec,
    BootstrapSpec,
    CSCVSpec,
    DataSnoopingSpec,
    DeflatedSharpeRatioSpec,
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
    HACKernel,
    ParameterDistanceMetric,
    ReturnConvention,
    RobustnessPerformanceMetric,
    RobustnessRankTieMethod,
    RobustnessWinnerTiePolicy,
)
from backtest_auditor.domain.issues import InputValidationError
from backtest_auditor.domain.metadata import ReturnConstructionSpec
from backtest_auditor.domain.reproducibility import AuditRunSpec
from backtest_auditor.ingestion.ibkr_flex import IBKR_FLEX_DATE_FORMATS
from backtest_auditor.integrations.ibkr_flex import IbkrFlexError
from backtest_auditor.persistence.sqlalchemy_repository import (
    PersistenceError,
    SQLAlchemyAuditRepository,
)
from backtest_auditor.presentation.streamlit_controller import (
    AuditPresentation,
    BenchmarkInput,
    CalendarInput,
    ExperimentFamilyRequest,
    ImplementationRiskPresentation,
    ImplementationRiskRequest,
    IbkrFlexImportPresentation,
    IbkrFlexImportRequest,
    SingleRunRequest,
    UploadedInput,
    run_family_audit,
    run_implementation_risk_audit,
    run_ibkr_flex_import,
    run_single_audit,
    presentation_to_snapshot,
)


def _stretch_kwargs() -> dict[str, Any]:
    """Use the current width API without dropping declared Streamlit support."""
    width = inspect.signature(st.dataframe).parameters.get("width")
    if width is not None and width.default == "stretch":
        return {"width": "stretch"}
    return {"use_container_width": True}


def main() -> None:
    st.set_page_config(
        page_title="Backtest Integrity Auditor",
        page_icon="✓",
        layout="wide",
    )
    st.title("Backtest Integrity Auditor")
    st.caption(
        f"Package {PACKAGE_VERSION} · report schema {REPORT_SCHEMA_VERSION} · "
        "evidence in, deterministic audit out"
    )
    st.info(
        "This interface audits supplied evidence and can import IBKR Activity "
        "Flex statements through a read-only adapter. It does not run strategies, "
        "select parameters, reconstruct trades, or place orders.",
        icon="ℹ️",
    )
    mode = st.sidebar.radio(
        "Audit workflow",
        (
            "Single-Run",
            "Experiment-Family",
            "Implementation Risk",
            "IBKR Flex Import",
            "Audit History",
        ),
    )
    st.sidebar.markdown(
        "Original uploads are temporary. Only deterministic reports and canonical "
        "normalized returns are retained when you explicitly save an audit."
    )

    try:
        submitted: (
            SingleRunRequest
            | ExperimentFamilyRequest
            | IbkrFlexImportRequest
            | ImplementationRiskRequest
            | None
        )
        if mode == "Single-Run":
            submitted = _single_run_panel()
        elif mode == "Experiment-Family":
            submitted = _family_panel()
        elif mode == "IBKR Flex Import":
            submitted = _ibkr_flex_panel()
        elif mode == "Implementation Risk":
            submitted = _implementation_risk_panel()
        else:
            submitted = None
            _history_panel()

        if submitted is not None:
            with st.spinner("Auditing supplied evidence…"):
                result = (
                    run_single_audit(submitted)
                    if isinstance(submitted, SingleRunRequest)
                    else (
                        run_family_audit(submitted)
                        if isinstance(submitted, ExperimentFamilyRequest)
                        else (
                            run_implementation_risk_audit(submitted)
                            if isinstance(submitted, ImplementationRiskRequest)
                            else run_ibkr_flex_import(submitted)
                        )
                    )
                )
            if isinstance(result, IbkrFlexImportPresentation):
                st.session_state["ibkr_import_result"] = result
            elif isinstance(result, ImplementationRiskPresentation):
                st.session_state["implementation_risk_result"] = result
            else:
                st.session_state["audit_result"] = result
    except InputValidationError as error:
        st.error("The uploaded evidence failed canonical input validation.")
        st.dataframe(
            [_issue_row(issue) for issue in error.issues],
            hide_index=True,
            **_stretch_kwargs(),
        )
    except PersistenceError as error:
        st.error(str(error))
    except IbkrFlexError as error:
        st.error(f"IBKR Flex import failed: {error}")
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        st.error(f"Configuration error: {error}")

    if mode == "IBKR Flex Import":
        imported = st.session_state.get("ibkr_import_result")
        if isinstance(imported, IbkrFlexImportPresentation):
            _render_ibkr_flex_import(imported)
    elif mode == "Implementation Risk":
        implementation_result = st.session_state.get("implementation_risk_result")
        if isinstance(implementation_result, ImplementationRiskPresentation):
            _render_implementation_risk(implementation_result)
    else:
        result = st.session_state.get("audit_result")  # type: ignore[assignment]  # QUALITY.md
        if isinstance(result, AuditPresentation):
            _render_result(result)


def _implementation_risk_panel() -> ImplementationRiskRequest | None:
    st.header("Cross-engine implementation-risk audit")
    st.caption(
        "Upload canonical V1.5C ZIP bundles and the four explicit policy files. "
        "The auditor compares exported evidence and never executes a backtest."
    )
    bundles_tab, policies_tab, manifest_tab = st.tabs(
        ("Bundles", "Policies", "Reproducibility")
    )
    with bundles_tab:
        reference = st.file_uploader(
            "Reference canonical bundle ZIP",
            type=("zip",),
            key="implementation_reference",
        )
        candidates = st.file_uploader(
            "Candidate canonical bundle ZIPs",
            type=("zip",),
            accept_multiple_files=True,
            key="implementation_candidates",
        )
    with policies_tab:
        normalization = st.file_uploader(
            "Normalization plan JSON",
            type=("json",),
            key="implementation_normalization",
        )
        comparison = st.file_uploader(
            "Comparison policy JSON", type=("json",), key="implementation_comparison"
        )
        measurement = st.file_uploader(
            "Divergence measurement policy JSON",
            type=("json",),
            key="implementation_measurement",
        )
        assessment = st.file_uploader(
            "Risk assessment policy JSON",
            type=("json",),
            key="implementation_assessment",
        )
    with manifest_tab:
        manifest_values = _manifest_widgets("implementation")
    if not st.button("Audit implementation risk", type="primary"):
        return None
    st.session_state.pop("implementation_risk_result", None)
    if reference is None or not candidates:
        raise ValueError("One reference and at least one candidate ZIP are required.")
    if any(
        item is None for item in (normalization, comparison, measurement, assessment)
    ):
        raise ValueError("All four implementation-risk policy files are required.")
    return ImplementationRiskRequest(
        _upload(reference),
        tuple(_upload(item) for item in candidates),
        _upload(normalization),
        _upload(comparison),
        _upload(measurement),
        _upload(assessment),
        _manifest(manifest_values),
    )


def _ibkr_flex_panel() -> IbkrFlexImportRequest | None:
    st.header("IBKR Activity Flex import")
    st.caption(
        "Imports period-level Change in NAV TWR. Each statement interval becomes "
        "one observation; no daily returns are inferred."
    )
    source_mode = st.radio(
        "Source",
        ("Exported files", "Read-only Flex Web Service"),
        horizontal=True,
    )
    files: list[Any] = []
    query_id = ""
    requested_from_date = None
    requested_to_date = None
    if source_mode == "Exported files":
        files = st.file_uploader(
            "Activity Flex XML/CSV statements",
            type=("xml", "csv"),
            accept_multiple_files=True,
            key="ibkr_flex_files",
        )
    else:
        token_available = bool(os.environ.get("BACKTEST_AUDITOR_IBKR_FLEX_TOKEN", ""))
        environment_query_id = os.environ.get("BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID", "")
        st.caption(
            "Flex token environment variable: "
            + ("available" if token_available else "not configured")
            + ". The token is never entered into or returned by this interface."
        )
        query_id = st.text_input(
            "Flex query ID",
            "",
            type="password",
            placeholder=(
                "Using environment configuration"
                if environment_query_id
                else "Required"
            ),
        )
        override_dates = st.checkbox("Override the query date range")
        date_left, date_right = st.columns(2)
        with date_left:
            from_value = st.date_input("From date", disabled=not override_dates)
        with date_right:
            to_value = st.date_input("To date", disabled=not override_dates)
        if override_dates:
            requested_from_date = from_value
            requested_to_date = to_value

    selector_left, selector_right = st.columns(2)
    with selector_left:
        account_id = st.text_input(
            "Account ID selector (optional)",
            "",
            type="password",
            help="Needed only for multi-account statements; stored only as a hash.",
        )
    with selector_right:
        model = st.text_input("Model selector (optional)", "")
    declaration_left, declaration_right, declaration_third = st.columns(3)
    with declaration_left:
        date_format = st.selectbox(
            "Configured Flex date format",
            tuple(IBKR_FLEX_DATE_FORMATS),
        )
    with declaration_right:
        declared_frequency = st.text_input("Declared frequency (optional)", "")
    with declaration_third:
        declare_scale = st.checkbox("Declare periods per year", key="ibkr_scale")
        periods_per_year = st.number_input(
            "Periods per year",
            min_value=1,
            value=252,
            disabled=not declare_scale,
            key="ibkr_periods_per_year",
        )

    if not st.button("Import IBKR Flex evidence", type="primary"):
        return None
    st.session_state.pop("ibkr_import_result", None)
    optional_account = _optional_text(account_id)
    optional_model = _optional_text(model)
    if optional_model is not None and optional_account is None:
        raise ValueError("A model selector requires an account ID selector.")
    if source_mode == "Exported files":
        if not files:
            raise ValueError("At least one Activity Flex XML/CSV file is required.")
        return IbkrFlexImportRequest(
            source_mode="files",
            statement_files=tuple(_upload(item) for item in files),
            account_id=optional_account,
            model=optional_model,
            date_format=date_format,
            declared_frequency=_optional_text(declared_frequency),
            periods_per_year=(int(periods_per_year) if declare_scale else None),
        )
    token = os.environ.get("BACKTEST_AUDITOR_IBKR_FLEX_TOKEN", "")
    effective_query_id = query_id or os.environ.get(
        "BACKTEST_AUDITOR_IBKR_FLEX_QUERY_ID", ""
    )
    if not token:
        raise ValueError("BACKTEST_AUDITOR_IBKR_FLEX_TOKEN is not configured.")
    if not effective_query_id:
        raise ValueError("A Flex query ID is required.")
    return IbkrFlexImportRequest(
        source_mode="api",
        token=token,
        query_id=effective_query_id,
        requested_from_date=requested_from_date,
        requested_to_date=requested_to_date,
        account_id=optional_account,
        model=optional_model,
        date_format=date_format,
        declared_frequency=_optional_text(declared_frequency),
        periods_per_year=int(periods_per_year) if declare_scale else None,
    )


def _render_ibkr_flex_import(result: IbkrFlexImportPresentation) -> None:
    st.success("IBKR Flex evidence was canonicalized without persisting credentials.")
    first, second, third = st.columns(3)
    first.metric("Statement intervals", result.period_count)
    second.metric("First period start", result.first_period_start)
    third.metric("Last period end", result.last_period_end)
    if result.warning_codes:
        st.warning("Canonicalization warnings: " + ", ".join(result.warning_codes))
    st.code(result.import_sha256, language=None)
    download_left, download_right = st.columns(2)
    with download_left:
        st.download_button(
            "Download canonical returns CSV",
            result.canonical_csv,
            file_name="ibkr-flex-returns.csv",
            mime="text/csv",
        )
    with download_right:
        st.download_button(
            "Download import manifest JSON",
            result.manifest_json,
            file_name="ibkr-flex-import.json",
            mime="application/json",
        )
    st.info(
        "Use the canonical CSV in the Single-Run workflow. Keep the import "
        "manifest beside it as source-provenance evidence."
    )


def _single_run_panel() -> SingleRunRequest | None:
    st.header("Single-Run audit")
    files_tab, declarations_tab, methods_tab, manifest_tab = st.tabs(
        ("Files", "Declarations", "Methods", "Reproducibility")
    )
    with files_tab:
        left, right = st.columns(2)
        with left:
            returns_file = st.file_uploader(
                "Strategy returns CSV",
                type=("csv",),
                key="single_returns",
            )
            run_id = st.text_input("Run ID", "streamlit-run")
            timestamp_column = st.text_input("Timestamp column", "timestamp")
            return_column = st.text_input("Return column", "return")
            return_convention = st.selectbox(
                "Return convention", tuple(item.value for item in ReturnConvention)
            )
        with right:
            use_benchmark = st.checkbox("Include benchmark")
            benchmark_file = st.file_uploader(
                "Benchmark returns CSV",
                type=("csv",),
                disabled=not use_benchmark,
                key="single_benchmark",
            )
            benchmark_id = st.text_input(
                "Benchmark ID", "benchmark", disabled=not use_benchmark
            )
            benchmark_timestamp_column = st.text_input(
                "Benchmark timestamp column",
                "timestamp",
                disabled=not use_benchmark,
            )
            benchmark_return_column = st.text_input(
                "Benchmark return column", "return", disabled=not use_benchmark
            )
            benchmark_convention = st.selectbox(
                "Benchmark return convention",
                tuple(item.value for item in ReturnConvention),
                disabled=not use_benchmark,
            )

        st.markdown("#### Additive evidence")
        risk_free_column, gross_column, regime_column_widgets = st.columns(3)
        with risk_free_column:
            use_risk_free_series = st.checkbox("Include period risk-free series")
            risk_free_file = st.file_uploader(
                "Risk-free returns CSV",
                type=("csv",),
                disabled=not use_risk_free_series,
                key="single_risk_free",
            )
            risk_free_timestamp_column = st.text_input(
                "Risk-free timestamp column",
                "timestamp",
                disabled=not use_risk_free_series,
            )
            risk_free_return_column = st.text_input(
                "Risk-free return column",
                "return",
                disabled=not use_risk_free_series,
            )
            risk_free_convention = st.selectbox(
                "Risk-free return convention",
                tuple(item.value for item in ReturnConvention),
                disabled=not use_risk_free_series,
            )
        with gross_column:
            use_gross_returns = st.checkbox("Include gross strategy returns")
            gross_returns_file = st.file_uploader(
                "Gross returns CSV",
                type=("csv",),
                disabled=not use_gross_returns,
                key="single_gross_returns",
            )
            gross_timestamp_column = st.text_input(
                "Gross timestamp column",
                "timestamp",
                disabled=not use_gross_returns,
            )
            gross_return_column = st.text_input(
                "Gross return column",
                "return",
                disabled=not use_gross_returns,
            )
            gross_convention = st.selectbox(
                "Gross return convention",
                tuple(item.value for item in ReturnConvention),
                disabled=not use_gross_returns,
            )
        with regime_column_widgets:
            use_regimes = st.checkbox("Include declared regimes")
            regimes_file = st.file_uploader(
                "Regimes CSV",
                type=("csv",),
                disabled=not use_regimes,
                key="single_regimes",
            )
            regime_timestamp_column = st.text_input(
                "Regime timestamp column",
                "timestamp",
                disabled=not use_regimes,
            )
            regime_column = st.text_input(
                "Regime label column",
                "regime",
                disabled=not use_regimes,
            )

    with declarations_tab:
        sampling_left, sampling_right = st.columns(2)
        with sampling_left:
            declared_frequency = st.text_input(
                "Declared pandas frequency alias (optional)", ""
            )
            declare_scale = st.checkbox("Declare periods per year")
            periods_per_year = st.number_input(
                "Periods per year",
                min_value=1,
                value=252,
                disabled=not declare_scale,
            )
            timestamp_timezone = st.text_input(
                "Strategy timestamp timezone (optional)", ""
            )
            benchmark_timezone = st.text_input(
                "Benchmark timestamp timezone (optional)",
                "",
                disabled=not use_benchmark,
            )
        with sampling_right:
            strategy_calendar = _calendar_widgets("Strategy", "strategy_calendar")
            benchmark_calendar = _calendar_widgets(
                "Benchmark",
                "benchmark_calendar",
                disabled=not use_benchmark,
            )
        st.markdown("#### Return-construction declarations")
        st.caption(
            "Optional JSON uses the ReturnConstructionSpec field names. "
            "Omitted declarations remain explicitly unavailable in the report."
        )
        construction_left, construction_right = st.columns(2)
        with construction_left:
            strategy_construction_json = st.text_area(
                "Strategy methodology JSON",
                "",
                placeholder=_construction_example(),
            )
        with construction_right:
            benchmark_construction_json = st.text_area(
                "Benchmark methodology JSON",
                "",
                placeholder=_construction_example(),
                disabled=not use_benchmark,
            )

    with methods_tab:
        method_left, method_right = st.columns(2)
        with method_left:
            use_sharpe = st.checkbox("Annualized Sharpe", value=True)
            risk_free_rate = st.number_input(
                "Annual risk-free rate",
                value=0.0,
                format="%.6f",
                disabled=not use_sharpe,
            )
            use_psr = st.checkbox("Probabilistic Sharpe Ratio")
            psr_benchmark = st.number_input(
                "PSR benchmark annualized Sharpe",
                value=0.0,
                format="%.6f",
                disabled=not use_psr,
            )
            psr_confidence = st.number_input(
                "Required PSR confidence",
                min_value=0.500001,
                max_value=0.999999,
                value=0.95,
                format="%.6f",
                disabled=not use_psr,
            )
            use_serial = st.checkbox("Serial-dependence diagnostic")
            serial_lag = st.number_input(
                "Serial maximum lag", min_value=1, value=5, disabled=not use_serial
            )
            serial_alpha = st.number_input(
                "Serial significance level",
                min_value=0.000001,
                max_value=0.999999,
                value=0.05,
                format="%.6f",
                disabled=not use_serial,
            )
        with method_right:
            use_hac = st.checkbox("Bartlett-HAC Sharpe adjustment")
            hac_lag = st.number_input(
                "HAC maximum lag", min_value=1, value=5, disabled=not use_hac
            )
            use_bootstrap = st.checkbox("Dependent-data bootstrap")
            bootstrap_method = st.selectbox(
                "Bootstrap method",
                tuple(item.value for item in BootstrapMethod),
                disabled=not use_bootstrap,
            )
            bootstrap_replications = st.number_input(
                "Bootstrap replications",
                min_value=2,
                value=1000,
                disabled=not use_bootstrap,
            )
            bootstrap_confidence = st.number_input(
                "Bootstrap confidence",
                min_value=0.500001,
                max_value=0.999999,
                value=0.95,
                format="%.6f",
                disabled=not use_bootstrap,
            )
            bootstrap_block = st.number_input(
                "Block length / stationary mean block length",
                min_value=1,
                value=5,
                disabled=not use_bootstrap,
            )

        advanced_left, advanced_right = st.columns(2)
        with advanced_left:
            st.markdown("#### Downside and tail risk")
            use_advanced_risk = st.checkbox("Configure advanced risk statistics")
            minimum_acceptable_return = st.number_input(
                "Minimum acceptable period return",
                value=0.0,
                format="%.6f",
                disabled=not use_advanced_risk,
            )
            tail_confidence = st.number_input(
                "Historical tail confidence",
                min_value=0.500001,
                max_value=0.999999,
                value=0.95,
                format="%.6f",
                disabled=not use_advanced_risk,
            )
        with advanced_right:
            st.markdown("#### Benchmark alpha inference")
            use_benchmark_inference = st.checkbox(
                "Configure Bartlett-HAC alpha inference",
                disabled=not use_benchmark,
            )
            benchmark_alpha_lag = st.number_input(
                "Alpha HAC maximum lag",
                min_value=0,
                value=5,
                disabled=not (use_benchmark and use_benchmark_inference),
            )
            benchmark_alpha_confidence = st.number_input(
                "Alpha confidence level",
                min_value=0.500001,
                max_value=0.999999,
                value=0.95,
                format="%.6f",
                disabled=not (use_benchmark and use_benchmark_inference),
            )
            bootstrap_seed = st.number_input(
                "Bootstrap seed",
                min_value=0,
                value=42,
                disabled=not use_bootstrap,
            )

    with manifest_tab:
        manifest_values = _manifest_widgets("single")

    if not st.button("Run Single-Run audit", type="primary"):
        return None
    st.session_state.pop("audit_result", None)
    if returns_file is None:
        raise ValueError("Strategy returns CSV is required.")
    if use_risk_free_series and risk_free_file is None:
        raise ValueError("Risk-free returns CSV is required when enabled.")
    if use_gross_returns and gross_returns_file is None:
        raise ValueError("Gross returns CSV is required when enabled.")
    if use_regimes and regimes_file is None:
        raise ValueError("Regimes CSV is required when enabled.")
    benchmark = None
    if use_benchmark:
        if benchmark_file is None:
            raise ValueError("Benchmark returns CSV is required when enabled.")
        benchmark = BenchmarkInput(
            returns_file=_upload(benchmark_file),
            benchmark_id=benchmark_id,
            timestamp_column=benchmark_timestamp_column,
            return_column=benchmark_return_column,
            return_convention=ReturnConvention(benchmark_convention),
            timestamp_timezone=_optional_text(benchmark_timezone),
            observation_calendar=benchmark_calendar,
            return_construction=_construction(benchmark_construction_json),
        )
    return SingleRunRequest(
        returns_file=_upload(returns_file),
        run_id=run_id,
        timestamp_column=timestamp_column,
        return_column=return_column,
        return_convention=ReturnConvention(return_convention),
        declared_frequency=_optional_text(declared_frequency),
        periods_per_year=int(periods_per_year) if declare_scale else None,
        timestamp_timezone=_optional_text(timestamp_timezone),
        observation_calendar=strategy_calendar,
        return_construction=_construction(strategy_construction_json),
        benchmark=benchmark,
        risk_free_file=(_upload(risk_free_file) if use_risk_free_series else None),
        risk_free_timestamp_column=risk_free_timestamp_column,
        risk_free_return_column=risk_free_return_column,
        risk_free_return_convention=ReturnConvention(risk_free_convention),
        gross_returns_file=(_upload(gross_returns_file) if use_gross_returns else None),
        gross_timestamp_column=gross_timestamp_column,
        gross_return_column=gross_return_column,
        gross_return_convention=ReturnConvention(gross_convention),
        regimes_file=_upload(regimes_file) if use_regimes else None,
        regime_timestamp_column=regime_timestamp_column,
        regime_column=regime_column,
        sharpe_spec=(SharpeRatioSpec(risk_free_rate) if use_sharpe else None),
        psr_spec=(
            ProbabilisticSharpeRatioSpec(psr_benchmark, psr_confidence)
            if use_psr
            else None
        ),
        serial_dependence_spec=(
            SerialDependenceSpec(int(serial_lag), serial_alpha) if use_serial else None
        ),
        serial_adjustment_spec=(
            SerialAdjustmentSpec(int(hac_lag), HACKernel.BARTLETT) if use_hac else None
        ),
        bootstrap_spec=(
            BootstrapSpec(
                BootstrapMethod(bootstrap_method),
                BootstrapIntervalMethod.PERCENTILE,
                int(bootstrap_replications),
                bootstrap_confidence,
                int(bootstrap_block),
                int(bootstrap_seed),
            )
            if use_bootstrap
            else None
        ),
        advanced_risk_spec=(
            AdvancedRiskSpec(minimum_acceptable_return, tail_confidence)
            if use_advanced_risk
            else None
        ),
        benchmark_inference_spec=(
            BenchmarkInferenceSpec(int(benchmark_alpha_lag), benchmark_alpha_confidence)
            if use_benchmark and use_benchmark_inference
            else None
        ),
        run_manifest_spec=_manifest(manifest_values),
    )


def _family_panel() -> ExperimentFamilyRequest | None:
    st.header("Experiment-Family audit")
    files_tab, methods_tab, manifest_tab = st.tabs(
        ("Files", "Family methods", "Reproducibility")
    )
    with files_tab:
        first, second, third = st.columns(3)
        with first:
            manifest_file = st.file_uploader(
                "Family manifest JSON", type=("json",), key="family_manifest_file"
            )
            splits_file = st.file_uploader(
                "Split membership CSV (optional)",
                type=("csv",),
                key="family_splits",
            )
        with second:
            trials_file = st.file_uploader(
                "Trial inventory CSV", type=("csv",), key="family_trials"
            )
            benchmark_file = st.file_uploader(
                "Shared benchmark CSV (optional)",
                type=("csv",),
                key="family_benchmark",
            )
        with third:
            returns_file = st.file_uploader(
                "Trial returns CSV", type=("csv",), key="family_returns"
            )
        st.caption(
            "The manifest controls the family sampling, return convention, "
            "selection rule, parameter schema, and benchmark contract."
        )

    with methods_tab:
        dsr_column, cscv_column = st.columns(2)
        with dsr_column:
            st.markdown("#### Deflated Sharpe Ratio")
            use_dsr = st.checkbox("Configure classical DSR")
            dsr_risk_free = st.number_input(
                "DSR annual risk-free rate",
                value=0.0,
                format="%.6f",
                disabled=not use_dsr,
            )
            dsr_confidence = st.number_input(
                "DSR required confidence",
                min_value=0.500001,
                max_value=0.999999,
                value=0.95,
                format="%.6f",
                disabled=not use_dsr,
            )
            use_effective_count = st.checkbox(
                "Supply external effective trial count", disabled=not use_dsr
            )
            effective_count = st.number_input(
                "Effective independent trials",
                min_value=1,
                value=2,
                disabled=not (use_dsr and use_effective_count),
            )
            effective_method = st.text_input(
                "Effective-count methodology",
                "",
                disabled=not (use_dsr and use_effective_count),
            )
        with cscv_column:
            st.markdown("#### CSCV / PBO")
            use_cscv = st.checkbox("Configure exhaustive CSCV")
            cscv_metric = st.text_input(
                "CSCV selection metric name",
                "period_sharpe_ratio",
                disabled=not use_cscv,
            )
            cscv_partitions = st.number_input(
                "CSCV even partition count",
                min_value=2,
                value=4,
                step=2,
                disabled=not use_cscv,
            )
            cscv_risk_free = st.number_input(
                "CSCV annual risk-free rate",
                value=0.0,
                format="%.6f",
                disabled=not use_cscv,
            )
            cscv_limit = st.number_input(
                "CSCV maximum combinations",
                min_value=1,
                value=1000,
                disabled=not use_cscv,
            )
            cscv_max_pbo = st.number_input(
                "Maximum acceptable PBO",
                min_value=0.000001,
                max_value=0.999999,
                value=0.05,
                format="%.6f",
                disabled=not use_cscv,
            )

        parameter_column, temporal_column = st.columns(2)
        with parameter_column:
            st.markdown("#### Parameter neighborhood")
            use_parameter = st.checkbox("Configure parameter robustness")
            parameter_metric = st.text_input(
                "Parameter selection metric name",
                "period_sharpe_ratio",
                disabled=not use_parameter,
            )
            parameter_risk_free = st.number_input(
                "Parameter annual risk-free rate",
                value=0.0,
                format="%.6f",
                disabled=not use_parameter,
            )
            parameter_scales = st.text_area(
                "Parameter scales JSON",
                '{"lookback": 10.0}',
                disabled=not use_parameter,
            )
            maximum_distance = st.number_input(
                "Maximum standardized distance",
                min_value=0.000001,
                value=1.0,
                format="%.6f",
                disabled=not use_parameter,
            )
            minimum_neighbors = st.number_input(
                "Minimum neighbors",
                min_value=1,
                value=1,
                disabled=not use_parameter,
            )
            maximum_score_difference = st.number_input(
                "Maximum acceptable score difference",
                min_value=0.0,
                value=0.25,
                format="%.6f",
                disabled=not use_parameter,
            )
            minimum_neighbor_fraction = st.number_input(
                "Minimum acceptable neighbor fraction",
                min_value=0.0,
                max_value=1.0,
                value=0.5,
                format="%.6f",
                disabled=not use_parameter,
            )
        with temporal_column:
            st.markdown("#### Temporal / fold robustness")
            use_temporal = st.checkbox("Configure temporal robustness")
            temporal_metric = st.text_input(
                "Temporal selection metric name",
                "period_sharpe_ratio",
                disabled=not use_temporal,
            )
            temporal_risk_free = st.number_input(
                "Temporal annual risk-free rate",
                value=0.0,
                format="%.6f",
                disabled=not use_temporal,
            )
            temporal_windows = st.number_input(
                "Equal temporal windows",
                min_value=2,
                value=4,
                disabled=not use_temporal,
            )
            minimum_top_half = st.number_input(
                "Minimum selected top-half fraction",
                min_value=0.0,
                max_value=1.0,
                value=0.5,
                format="%.6f",
                disabled=not use_temporal,
            )
            maximum_below_zero = st.number_input(
                "Maximum selected below-zero fraction",
                min_value=0.0,
                max_value=1.0,
                value=0.25,
                format="%.6f",
                disabled=not use_temporal,
            )

        st.markdown("#### Benchmark-relative data-snooping controls")
        data_left, data_right = st.columns(2)
        with data_left:
            use_data_snooping = st.checkbox(
                "Configure White Reality Check and Hansen SPA",
                disabled=benchmark_file is None,
            )
            data_snooping_replications = st.number_input(
                "Stationary-bootstrap replications",
                min_value=2,
                value=1000,
                disabled=not use_data_snooping,
            )
            data_snooping_block = st.number_input(
                "Mean block length",
                min_value=1,
                value=5,
                disabled=not use_data_snooping,
            )
        with data_right:
            data_snooping_seed = st.number_input(
                "Data-snooping seed",
                min_value=0,
                value=42,
                disabled=not use_data_snooping,
            )
            data_snooping_significance = st.number_input(
                "Data-snooping significance level",
                min_value=0.000001,
                max_value=0.499999,
                value=0.05,
                format="%.6f",
                disabled=not use_data_snooping,
            )

    with manifest_tab:
        manifest_values = _manifest_widgets("family")

    if not st.button("Run Experiment-Family audit", type="primary"):
        return None
    st.session_state.pop("audit_result", None)
    if manifest_file is None or trials_file is None or returns_file is None:
        raise ValueError("Manifest, trial inventory, and trial returns are required.")
    if use_data_snooping and benchmark_file is None:
        raise ValueError("A shared benchmark is required for data-snooping tests.")
    return ExperimentFamilyRequest(
        manifest_file=_upload(manifest_file),
        trials_file=_upload(trials_file),
        returns_file=_upload(returns_file),
        splits_file=_optional_upload(splits_file),
        benchmark_file=_optional_upload(benchmark_file),
        dsr_spec=(
            DeflatedSharpeRatioSpec(
                DeflatedSharpeRatioMethod.CLASSIC_EXPECTED_MAXIMUM,
                DSRTrialCountPolicy.SELECTION_ELIGIBLE,
                dsr_risk_free,
                dsr_confidence,
                int(effective_count) if use_effective_count else None,
                effective_method if use_effective_count else None,
            )
            if use_dsr
            else None
        ),
        cscv_spec=(
            CSCVSpec(
                CSCVMethod.COMBINATORIALLY_SYMMETRIC,
                CSCVPerformanceMetric.PERIOD_SHARPE_RATIO,
                cscv_metric,
                int(cscv_partitions),
                cscv_risk_free,
                int(cscv_limit),
                CSCVRankTieMethod.AVERAGE,
                CSCVWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
                cscv_max_pbo,
            )
            if use_cscv
            else None
        ),
        parameter_robustness_spec=(
            ParameterRobustnessSpec(
                RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
                parameter_metric,
                parameter_risk_free,
                ParameterDistanceMetric.STANDARDIZED_EUCLIDEAN,
                _parameter_scales(parameter_scales),
                maximum_distance,
                int(minimum_neighbors),
                maximum_score_difference,
                minimum_neighbor_fraction,
            )
            if use_parameter
            else None
        ),
        temporal_robustness_spec=(
            TemporalRobustnessSpec(
                RobustnessPerformanceMetric.PERIOD_SHARPE_RATIO,
                temporal_metric,
                temporal_risk_free,
                int(temporal_windows),
                RobustnessRankTieMethod.AVERAGE,
                RobustnessWinnerTiePolicy.FIRST_BY_ATTEMPT_INDEX,
                minimum_top_half,
                maximum_below_zero,
            )
            if use_temporal
            else None
        ),
        data_snooping_spec=(
            DataSnoopingSpec(
                int(data_snooping_replications),
                int(data_snooping_block),
                int(data_snooping_seed),
                data_snooping_significance,
            )
            if use_data_snooping
            else None
        ),
        run_manifest_spec=_manifest(manifest_values),
    )


def _calendar_widgets(
    label: str,
    key_prefix: str,
    *,
    disabled: bool = False,
) -> CalendarInput | None:
    use_calendar = st.checkbox(
        f"Declare {label.lower()} observation calendar",
        key=f"{key_prefix}_enabled",
        disabled=disabled,
    )
    calendar_name = st.text_input(
        f"{label} calendar name",
        "WEEKDAYS",
        key=f"{key_prefix}_name",
        disabled=disabled or not use_calendar,
    )
    timezone = st.text_input(
        f"{label} calendar timezone",
        "UTC",
        key=f"{key_prefix}_timezone",
        disabled=disabled or not use_calendar,
    )
    sessions = st.file_uploader(
        f"{label} authoritative sessions CSV (optional)",
        type=("csv",),
        key=f"{key_prefix}_sessions",
        disabled=disabled or not use_calendar,
    )
    session_column = st.text_input(
        f"{label} session-date column",
        "session",
        key=f"{key_prefix}_session_column",
        disabled=disabled or not use_calendar or sessions is None,
    )
    if disabled or not use_calendar:
        return None
    return CalendarInput(
        calendar_name=calendar_name,
        timezone=timezone,
        sessions_file=_optional_upload(sessions),
        session_column=session_column,
    )


def _manifest_widgets(key_prefix: str) -> tuple[bool, str, str, str]:
    enabled = st.checkbox(
        "Create deterministic audit-run manifest", key=f"{key_prefix}_manifest"
    )
    audit_id = st.text_input(
        "Audit ID", "", key=f"{key_prefix}_audit_id", disabled=not enabled
    )
    timestamp = st.text_input(
        "Audit timestamp (ISO 8601 with offset)",
        "",
        placeholder="2026-08-13T12:00:00Z",
        key=f"{key_prefix}_audit_timestamp",
        disabled=not enabled,
    )
    git_commit = st.text_input(
        "Git commit or source revision",
        "",
        key=f"{key_prefix}_git_commit",
        disabled=not enabled,
    )
    return enabled, audit_id, timestamp, git_commit


def _manifest(values: tuple[bool, str, str, str]) -> AuditRunSpec | None:
    enabled, audit_id, timestamp, git_commit = values
    if not enabled:
        return None
    parsed = datetime.fromisoformat(timestamp.strip().replace("Z", "+00:00"))
    return AuditRunSpec(audit_id, parsed, git_commit)


def _construction(raw: str) -> ReturnConstructionSpec | None:
    if not raw.strip():
        return None
    values = json.loads(raw)
    if not isinstance(values, dict):
        raise ValueError("return-construction JSON must be an object.")
    return ReturnConstructionSpec(**values)


def _parameter_scales(raw: str) -> tuple[ParameterScale, ...]:
    values = json.loads(raw)
    if not isinstance(values, dict) or not values:
        raise ValueError("parameter scales must be a non-empty JSON object.")
    return tuple(
        ParameterScale(str(name), value) for name, value in sorted(values.items())
    )


def _upload(upload: Any) -> UploadedInput:
    return UploadedInput(upload.name, upload.getvalue())


def _optional_upload(upload: Any | None) -> UploadedInput | None:
    return None if upload is None else _upload(upload)


def _optional_text(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _render_result(result: AuditPresentation) -> None:
    st.divider()
    st.header("Audit result")
    first, second, third = st.columns(3)
    first.metric("Audit type", result.audit_type)
    second.metric("Subject", result.subject_id)
    third.metric("Findings", len(_rows(result.payload, "findings")))

    if st.button("Save audit to database", type="primary"):
        with _repository() as repository:
            saved = repository.save(presentation_to_snapshot(result))
        message = "Audit saved." if saved.created else "Identical audit already saved."
        st.success(f"{message} Database ID: {saved.audit_id}")

    profile_tab, findings_tab, issues_tab, report_tab = st.tabs(
        ("Evidence profile", "Findings", "Input issues", "Report")
    )
    with profile_tab:
        profile = result.payload.get("evidence_profile", {})
        dimensions = profile.get("dimensions", []) if isinstance(profile, dict) else []
        st.dataframe(
            dimensions,
            hide_index=True,
            **_stretch_kwargs(),
        )
        if isinstance(profile, dict):
            st.caption(str(profile.get("interpretation_boundary", "")))
    with findings_tab:
        findings = _rows(result.payload, "findings")
        if findings:
            st.dataframe(findings, hide_index=True, **_stretch_kwargs())
        else:
            st.success("No audit findings were generated.")
    with issues_tab:
        issues = _rows(result.payload, "input_issues")
        if issues:
            st.dataframe(issues, hide_index=True, **_stretch_kwargs())
        else:
            st.success("No non-blocking normalization issues were preserved.")
    with report_tab:
        json_column, markdown_column = st.columns(2)
        stem = _download_stem(result)
        json_column.download_button(
            "Download JSON",
            result.json_report,
            file_name=f"{stem}.json",
            mime="application/json",
            **_stretch_kwargs(),
        )
        markdown_column.download_button(
            "Download Markdown",
            result.markdown_report,
            file_name=f"{stem}.md",
            mime="text/markdown",
            **_stretch_kwargs(),
        )
        with st.expander("Preview deterministic JSON"):
            st.code(result.json_report, language="json")


def _render_implementation_risk(result: ImplementationRiskPresentation) -> None:
    st.divider()
    st.header("Implementation-risk result")
    first, second, third = st.columns(3)
    first.metric("Reconciliation", result.reconciliation_id)
    second.metric("Candidates", result.candidate_count)
    third.metric("Independent findings", len(_rows(result.payload, "findings")))
    st.info(str(result.payload.get("interpretation_boundary", "")), icon="ℹ️")

    candidates_tab, findings_tab, normalization_tab, report_tab = st.tabs(
        ("Candidates", "Findings", "Normalization", "Report")
    )
    with candidates_tab:
        rows = []
        for candidate in _rows(result.payload, "candidates"):
            run = candidate.get("candidate_run", {})
            if isinstance(run, dict):
                rows.append(
                    {
                        "run_id": run.get("run_id"),
                        "engine": run.get("engine_name"),
                        "score": candidate.get("implementation_risk_score"),
                        "uncertainty": candidate.get("uncertainty"),
                        "score_withheld_reason": candidate.get("score_withheld_reason"),
                    }
                )
        st.dataframe(rows, hide_index=True, **_stretch_kwargs())
    with findings_tab:
        findings = _rows(result.payload, "findings")
        if findings:
            st.dataframe(findings, hide_index=True, **_stretch_kwargs())
        else:
            st.success("No independent findings were generated.")
    with normalization_tab:
        normalization = result.payload.get("normalization", {})
        runs = normalization.get("runs", []) if isinstance(normalization, dict) else []
        st.dataframe(runs, hide_index=True, **_stretch_kwargs())
    with report_tab:
        json_column, markdown_column = st.columns(2)
        stem = _safe_stem(result.reconciliation_id)
        json_column.download_button(
            "Download JSON",
            result.json_report,
            file_name=f"implementation-risk-{stem}.json",
            mime="application/json",
            **_stretch_kwargs(),
        )
        markdown_column.download_button(
            "Download Markdown",
            result.markdown_report,
            file_name=f"implementation-risk-{stem}.md",
            mime="text/markdown",
            **_stretch_kwargs(),
        )
        with st.expander("Preview deterministic JSON"):
            st.code(result.json_report, language="json")


def _rows(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _issue_row(issue: Any) -> dict[str, object]:
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "blocking": issue.blocking,
        "message": issue.message,
        "location": issue.location,
    }


def _download_stem(result: AuditPresentation) -> str:
    safe_subject = _safe_stem(result.subject_id)
    return f"backtest-audit-{safe_subject or 'report'}"


def _safe_stem(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in value
    ).strip("-")


def _repository() -> SQLAlchemyAuditRepository:
    database_url = os.environ.get(
        "BACKTEST_AUDITOR_DATABASE_URL", "sqlite:///backtest_auditor.db"
    )
    return SQLAlchemyAuditRepository(database_url)


def _history_panel() -> None:
    st.header("Audit history")
    with _repository() as repository:
        summaries = repository.list(limit=250)
        st.caption(f"Database backend: {repository.backend}")
        if not summaries:
            st.info("No saved audits yet.")
            return
        st.dataframe(
            [
                {
                    "database_id": item.audit_id,
                    "created_at": item.created_at,
                    "audit_type": item.audit_type,
                    "subject": item.subject_id,
                    "package": item.package_version,
                    "schema": item.report_schema_version,
                    "series": item.series_count,
                    "observations": item.observation_count,
                }
                for item in summaries
            ],
            hide_index=True,
            **_stretch_kwargs(),
        )
        selected_id = st.selectbox(
            "Saved audit",
            tuple(item.audit_id for item in summaries),
            format_func=lambda audit_id: next(
                f"{item.created_at} · {item.audit_type} · {item.subject_id}"
                for item in summaries
                if item.audit_id == audit_id
            ),
        )
        if st.button("Open saved audit"):
            stored = repository.get(selected_id)
            if stored is None:
                st.error("The selected audit no longer exists.")
                return
            payload = json.loads(stored.json_report)
            st.session_state["audit_result"] = AuditPresentation(
                audit_type=stored.summary.audit_type,
                subject_id=stored.summary.subject_id,
                payload=payload,
                json_report=stored.json_report,
                markdown_report=stored.markdown_report,
                normalized_series=stored.normalized_series,
                report_schema_version=stored.summary.report_schema_version,
                package_version=stored.summary.package_version,
            )


def _construction_example() -> str:
    return (
        '{"transaction_costs_included": true, "fees_included": true, '
        '"leverage_policy": "unlevered", "currency": "USD", '
        '"price_adjustment_policy": "adjusted"}'
    )


if __name__ == "__main__":
    main()
