import hashlib
import importlib.metadata
import json
import platform
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from backtest_auditor import PACKAGE_VERSION
from backtest_auditor.domain.experiment import ExperimentFamily
from backtest_auditor.domain.findings import AuditFinding
from backtest_auditor.domain.issues import ValidationIssue
from backtest_auditor.domain.reproducibility import (
    AuditRunManifestResult,
    AuditRunSpec,
    DependencyVersion,
    InputArtifactHash,
    ManifestWarning,
    MethodVersion,
)
from backtest_auditor.domain.runs import StrategyRun


RUN_MANIFEST_SCHEMA_VERSION = "1.1"
NORMALIZED_DATA_ENCODING = "canonical_json_float_hex_v1"

_METHOD_VERSIONS = {
    "advanced_downside_tail_statistics": "1.0",
    "annualized_statistics": "1.0",
    "audit_run_manifest": "1.0",
    "benchmark_comparison": "1.0",
    "benchmark_alpha_hac_inference": "1.0",
    "bootstrap_moving_block_percentile": "1.0",
    "bootstrap_stationary_percentile": "1.0",
    "cscv_pbo": "1.0",
    "deflated_sharpe_ratio": "1.0",
    "descriptive_statistics": "1.0",
    "distribution_statistics": "1.0",
    "declared_regime_analysis": "1.0",
    "evidence_profile": "1.0",
    "experiment_family_assessment": "1.0",
    "hac_serial_adjustment": "1.0",
    "hansen_spa": "1.0",
    "minimum_track_record_length": "1.0",
    "observation_calendar_assessment": "1.0",
    "parameter_neighborhood_robustness": "1.0",
    "performance_path": "1.0",
    "probabilistic_sharpe_ratio": "1.0",
    "return_construction_assessment": "1.0",
    "gross_net_cost_drag": "1.0",
    "sampling_assessment": "1.0",
    "serial_dependence_diagnostic": "1.0",
    "temporal_and_fold_robustness": "1.0",
    "time_varying_risk_free_evidence": "1.0",
    "white_reality_check": "1.0",
}
_DEPENDENCIES = ("numpy", "pandas", "scipy")


def build_single_run_manifest(
    *,
    spec: AuditRunSpec,
    input_artifacts: tuple[InputArtifactHash, ...],
    run: StrategyRun,
    report_schema_version: str,
    audit_configuration: dict[str, Any],
    configured_method_names: tuple[str, ...],
    random_seeds: tuple[tuple[str, int], ...],
    findings: tuple[AuditFinding, ...],
    input_issues: tuple[ValidationIssue, ...],
) -> AuditRunManifestResult:
    normalized_payload = {
        "audit_type": "single_run",
        "run_id": run.run_id,
        "strategy": _strategy_payload(run),
    }
    return _build_manifest(
        spec=spec,
        input_artifacts=input_artifacts,
        audit_type="single_run",
        subject_id=run.run_id,
        report_schema_version=report_schema_version,
        normalized_payload=normalized_payload,
        audit_configuration=audit_configuration,
        configured_method_names=configured_method_names,
        random_seeds=random_seeds,
        findings=findings,
        input_issues=input_issues,
    )


def build_experiment_family_manifest(
    *,
    spec: AuditRunSpec,
    input_artifacts: tuple[InputArtifactHash, ...],
    family: ExperimentFamily,
    report_schema_version: str,
    audit_configuration: dict[str, Any],
    configured_method_names: tuple[str, ...],
    findings: tuple[AuditFinding, ...],
    input_issues: tuple[ValidationIssue, ...],
    random_seeds: tuple[tuple[str, int], ...] = (),
) -> AuditRunManifestResult:
    normalized_payload = {
        "audit_type": "experiment_family",
        "family": _experiment_family_payload(family),
    }
    return _build_manifest(
        spec=spec,
        input_artifacts=input_artifacts,
        audit_type="experiment_family",
        subject_id=family.manifest.family_id,
        report_schema_version=report_schema_version,
        normalized_payload=normalized_payload,
        audit_configuration=audit_configuration,
        configured_method_names=configured_method_names,
        random_seeds=random_seeds,
        findings=findings,
        input_issues=input_issues,
    )


def canonical_configuration(values: dict[str, Any]) -> dict[str, Any]:
    """Convert explicit audit choices to a deterministic JSON-safe mapping."""

    normalized = _json_value(values)
    assert isinstance(normalized, dict)
    return normalized


def _build_manifest(
    *,
    spec: AuditRunSpec,
    input_artifacts: tuple[InputArtifactHash, ...],
    audit_type: str,
    subject_id: str,
    report_schema_version: str,
    normalized_payload: dict[str, Any],
    audit_configuration: dict[str, Any],
    configured_method_names: tuple[str, ...],
    random_seeds: tuple[tuple[str, int], ...],
    findings: tuple[AuditFinding, ...],
    input_issues: tuple[ValidationIssue, ...],
) -> AuditRunManifestResult:
    artifacts = tuple(sorted(input_artifacts, key=lambda item: item.role))
    if not artifacts:
        raise ValueError("a run manifest requires at least one input artifact hash.")
    roles = tuple(item.role for item in artifacts)
    if len(set(roles)) != len(roles):
        raise ValueError("input artifact roles must be unique.")
    configuration_json = _canonical_json(audit_configuration)
    normalized_json = _canonical_json(normalized_payload)
    configuration_sha256 = _sha256_text(configuration_json)
    normalized_sha256 = _sha256_text(normalized_json)
    methods = tuple(
        MethodVersion(name=name, version=_METHOD_VERSIONS[name])
        for name in sorted(configured_method_names)
    )
    seeds = tuple(sorted(random_seeds))
    warnings = tuple(
        [
            ManifestWarning(source="input_issue", code=issue.code)
            for issue in input_issues
        ]
        + [
            ManifestWarning(source="audit_finding", code=finding.code)
            for finding in findings
        ]
    )
    dependencies = tuple(
        DependencyVersion(name=name, version=importlib.metadata.version(name))
        for name in _DEPENDENCIES
    )
    timestamp = spec.audit_timestamp.isoformat().replace("+00:00", "Z")
    public_body = {
        "manifest_schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "audit_id": spec.audit_id,
        "audit_timestamp_utc": timestamp,
        "audit_type": audit_type,
        "subject_id": subject_id,
        "package_version": PACKAGE_VERSION,
        "report_schema_version": report_schema_version,
        "git_commit": spec.git_commit,
        "input_artifacts": [_json_value(item) for item in artifacts],
        "normalized_data_encoding": NORMALIZED_DATA_ENCODING,
        "normalized_data_sha256": normalized_sha256,
        "configuration": audit_configuration,
        "configuration_sha256": configuration_sha256,
        "random_seeds": {name: seed for name, seed in seeds},
        "method_versions": [_json_value(item) for item in methods],
        "warnings": [_json_value(item) for item in warnings],
        "environment": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform_system": platform.system(),
            "platform_machine": platform.machine(),
            "dependencies": [_json_value(item) for item in dependencies],
        },
    }
    manifest_sha256 = _sha256_text(_canonical_json(public_body))
    return AuditRunManifestResult(
        manifest_schema_version=RUN_MANIFEST_SCHEMA_VERSION,
        audit_id=spec.audit_id,
        audit_timestamp_utc=timestamp,
        audit_type=audit_type,
        subject_id=subject_id,
        package_version=PACKAGE_VERSION,
        report_schema_version=report_schema_version,
        git_commit=spec.git_commit,
        input_artifacts=artifacts,
        normalized_data_encoding=NORMALIZED_DATA_ENCODING,
        normalized_data_sha256=normalized_sha256,
        configuration_json=configuration_json,
        configuration_sha256=configuration_sha256,
        random_seeds=seeds,
        method_versions=methods,
        warnings=warnings,
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        dependencies=dependencies,
        manifest_sha256=manifest_sha256,
    )


def _strategy_payload(run: StrategyRun) -> dict[str, Any]:
    return {
        "returns": _return_series_payload(run.returns),
        "risk_free_returns": (
            None
            if run.risk_free_returns is None
            else _return_series_payload(run.risk_free_returns)
        ),
        "gross_returns": (
            None
            if run.gross_returns is None
            else _return_series_payload(run.gross_returns)
        ),
        "regimes": (
            None
            if run.regimes is None
            else {
                "timestamps": [item.isoformat() for item in run.regimes.timestamps],
                "labels": list(run.regimes.labels),
            }
        ),
        "benchmark": (
            None
            if run.benchmark is None
            else {
                "benchmark_id": run.benchmark.benchmark_id,
                "returns": _return_series_payload(run.benchmark.returns),
            }
        ),
    }


def _experiment_family_payload(family: ExperimentFamily) -> dict[str, Any]:
    return {
        "manifest": _json_value(family.manifest),
        "trials": [_json_value(trial) for trial in family.trials],
        "return_matrix": {
            "timestamps": [item.isoformat() for item in family.returns.timestamps],
            "trial_ids": list(family.returns.trial_ids),
            "values_hex": [
                [float(value).hex() for value in row] for row in family.returns.values
            ],
            "convention": family.returns.convention.value,
            "sampling": _json_value(family.returns.sampling),
        },
        "splits": [_json_value(split) for split in family.splits],
        "benchmark_returns": (
            None
            if family.benchmark_returns is None
            else _return_series_payload(family.benchmark_returns)
        ),
    }


def _return_series_payload(series: Any) -> dict[str, Any]:
    return {
        "timestamps": [item.isoformat() for item in series.timestamps],
        "values_hex": [float(value).hex() for value in series.values],
        "convention": series.convention.value,
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("manifest configuration values must be finite.")
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        parsed = float(value)
        if not np.isfinite(parsed):
            raise ValueError("manifest values must be finite.")
        return parsed
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, pd.DatetimeIndex):
        return [item.isoformat() for item in value]
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported manifest value: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
