from __future__ import annotations

from pathlib import Path

import pytest

from backtest_auditor.cli import main
from backtest_auditor.implementation_risk import (
    MAX_IMPLEMENTATION_RISK_CANDIDATES,
    MAX_POLICY_JSON_BYTES,
    CanonicalArtifactFileBundleAdapter,
    ImplementationRiskAuditService,
    PolicyContractError,
    load_policy_json_file,
    parse_policy_json_bytes,
)
from backtest_auditor.presentation.streamlit_controller import (
    ImplementationRiskRequest,
    UploadedInput,
)
from scripts.generate_v1_5i_report_example import (
    _bundle,
    build_policies,
    generate_example,
)


def _cli_arguments(example: Path, output: Path) -> list[str]:
    return [
        "implementation-risk",
        str(example / "reference-bundle.zip"),
        str(example / "candidate-bundle.zip"),
        "--normalization-plan",
        str(example / "normalization-plan.json"),
        "--comparison-policy",
        str(example / "comparison-policy.json"),
        "--measurement-policy",
        str(example / "measurement-policy.json"),
        "--assessment-policy",
        str(example / "assessment-policy.json"),
        "--output",
        str(output),
    ]


def test_policy_file_boundary_is_bounded_utf8_regular_and_non_symlinked(
    tmp_path: Path,
) -> None:
    with pytest.raises(PolicyContractError, match="valid UTF-8"):
        parse_policy_json_bytes(b"\xff")
    with pytest.raises(PolicyContractError, match="safety limit"):
        parse_policy_json_bytes(b" " * (MAX_POLICY_JSON_BYTES + 1))

    policy = tmp_path / "policy.json"
    policy.write_text("{}", encoding="utf-8")
    link = tmp_path / "policy-link.json"
    link.symlink_to(policy)
    with pytest.raises(PolicyContractError, match="symbolic link"):
        load_policy_json_file(link)
    with pytest.raises(PolicyContractError, match="regular file"):
        load_policy_json_file(tmp_path / "missing.json")


def test_audit_service_caps_candidate_fanout_before_scope_construction() -> None:
    reference = _bundle(candidate=False)
    candidate = _bundle(candidate=True)
    policies = build_policies(reference, candidate)
    artifacts = (reference,) + (candidate,) * (MAX_IMPLEMENTATION_RISK_CANDIDATES + 1)

    with pytest.raises(ValueError, match="maximum"):
        ImplementationRiskAuditService(CanonicalArtifactFileBundleAdapter()).audit(
            artifacts,
            *policies,
        )


def test_streamlit_request_enforces_candidate_and_upload_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = UploadedInput("bundle.zip", b"zip")
    policy = UploadedInput("policy.json", b"{}")
    with pytest.raises(ValueError, match="maximum"):
        ImplementationRiskRequest(
            bundle,
            (bundle,) * (MAX_IMPLEMENTATION_RISK_CANDIDATES + 1),
            policy,
            policy,
            policy,
            policy,
        )

    monkeypatch.setattr(
        "backtest_auditor.presentation.streamlit_controller."
        "_MAX_IMPLEMENTATION_RISK_BUNDLE_UPLOAD_BYTES",
        2,
    )
    with pytest.raises(ValueError, match="bundle upload"):
        ImplementationRiskRequest(
            bundle,
            (bundle,),
            policy,
            policy,
            policy,
            policy,
        )

    monkeypatch.setattr(
        "backtest_auditor.presentation.streamlit_controller."
        "_MAX_IMPLEMENTATION_RISK_BUNDLE_UPLOAD_BYTES",
        10,
    )
    monkeypatch.setattr(
        "backtest_auditor.presentation.streamlit_controller.MAX_POLICY_JSON_BYTES",
        1,
    )
    with pytest.raises(ValueError, match="policy upload"):
        ImplementationRiskRequest(
            bundle,
            (bundle,),
            policy,
            policy,
            policy,
            policy,
        )


def test_cli_requires_explicit_force_and_never_replaces_an_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    example = tmp_path / "example"
    generate_example(example)
    output = tmp_path / "report.json"
    output.write_text("sentinel", encoding="utf-8")
    arguments = _cli_arguments(example, output)

    with pytest.raises(SystemExit):
        main(arguments)
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert "refusing to overwrite" in capsys.readouterr().err

    assert main([*arguments, "--force"]) == 0
    assert output.read_text(encoding="utf-8").startswith("{")

    policy = example / "normalization-plan.json"
    with pytest.raises(SystemExit):
        main(_cli_arguments(example, policy) + ["--force"])
    assert "must not replace an input" in capsys.readouterr().err

    directory_output = tmp_path / "report-directory"
    directory_output.mkdir()
    with pytest.raises(SystemExit):
        main(_cli_arguments(example, directory_output) + ["--force"])
    assert "regular file path" in capsys.readouterr().err


def test_cli_atomic_replace_preserves_prior_report_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    example = tmp_path / "example"
    generate_example(example)
    output = tmp_path / "report.json"
    output.write_text("previous-good-report", encoding="utf-8")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated atomic commit failure")

    monkeypatch.setattr("backtest_auditor.cli.os.replace", fail_replace)
    assert main([*_cli_arguments(example, output), "--force"]) == 3
    assert output.read_text(encoding="utf-8") == "previous-good-report"
    assert not tuple(tmp_path.glob(".report.json.*"))
    assert "simulated atomic commit failure" in capsys.readouterr().err
