import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_auditor.application.experiment_family_audit import (
    audit_experiment_family,
)
from backtest_auditor.application.single_run_audit import audit_single_run
from backtest_auditor.domain.evidence import EvidenceStatus
from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.runs import StrategyRun
from backtest_auditor.domain.series import ReturnSeries, SamplingSpec
from backtest_auditor.ingestion.experiment_family import (
    read_experiment_family_files,
)
from backtest_auditor.reporting.serialization import (
    evidence_profile_to_dict,
)


def test_single_profile_keeps_dimensions_independent_without_global_verdict() -> None:
    result = audit_single_run(
        StrategyRun(
            run_id="profile-test",
            returns=ReturnSeries(
                timestamps=pd.date_range("2026-01-01", periods=3, freq="D"),
                values=np.asarray([0.01, -0.005, 0.02]),
                convention=ReturnConvention.SIMPLE,
                sampling=SamplingSpec(),
            ),
        )
    )
    payload = evidence_profile_to_dict(result.evidence_profile)
    statuses = {item["dimension"]: item["status"] for item in payload["dimensions"]}

    assert payload["overall_status"] is None
    assert not hasattr(result.evidence_profile, "overall_status")
    assert "score" not in payload
    assert statuses["input_integrity"] == (
        EvidenceStatus.SUPPORTED_UNDER_STATED_ASSUMPTIONS
    )
    assert statuses["sampling_eligibility"] == EvidenceStatus.INELIGIBLE
    assert statuses["statistical_evidence"] == EvidenceStatus.INELIGIBLE
    assert statuses["reproducibility"] == EvidenceStatus.INSUFFICIENT_EVIDENCE
    assert "future performance" in payload["interpretation_boundary"]


def test_family_evidence_profile_matches_part_p_golden_fixture() -> None:
    normalized = read_experiment_family_files(
        "examples/experiment_family_manifest.json",
        "examples/experiment_family_trials.csv",
        "examples/experiment_family_returns.csv",
        splits_path="examples/experiment_family_splits.csv",
        benchmark_path="examples/sample_benchmark.csv",
    )
    result = audit_experiment_family(
        normalized.family,
        input_issues=normalized.issues,
    )
    expected = json.loads(
        Path("tests/fixtures/golden/part_p_family_evidence_profile.json").read_text(
            encoding="utf-8"
        )
    )

    assert evidence_profile_to_dict(result.evidence_profile) == expected
