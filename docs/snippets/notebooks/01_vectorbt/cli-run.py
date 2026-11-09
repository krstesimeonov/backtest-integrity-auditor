import json
import subprocess
import sys

command = [
    str(Path(sys.executable).with_name("backtest-auditor")),
    "implementation-risk",
    "reference.zip",
    "candidate.zip",
    "--normalization-plan", "normalization-plan.json",
    "--comparison-policy", "comparison-policy.json",
    "--measurement-policy", "measurement-policy.json",
    "--assessment-policy", "assessment-policy.json",
    "--format", "json",
    "--output", "report.json",
    "--force",
]  # fmt: skip
completed = subprocess.run(command, cwd=CLI_DIR, capture_output=True, text=True)
print("exit code:", completed.returncode, completed.stdout, completed.stderr)
cli_report = json.loads((CLI_DIR / "report.json").read_text(encoding="utf-8"))
kit.validate_report(cli_report)
print(
    "CLI report equals the report of the Python call above:",
    cli_report == correct.report,
)
