#!/usr/bin/env bash
# Build, check and smoke-test the distributions the way a new user meets them.
#
#   scripts/check_package.sh            # from the repository root
#
# 1. `python -m build` (sdist + wheel) and `twine check --strict dist/*`;
# 2. a brand-new venv (no system site-packages) that installs only the wheel;
# 3. from a directory outside the checkout, the Getting-started quickstart on
#    examples/quickstart/audit_returns.csv and the implementation-risk CLI
#    example, both through the installed console script;
# 4. pip-audit over the runtime dependencies that venv resolved.
#
# Outputs go to evidence/packaging/. BUILD_PYTHON (default .venv/bin/python)
# needs `build`, `twine` and `pip-audit`; BASE_PYTHON (default python3) is the
# interpreter the clean venv is created from.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BUILD_PYTHON="${BUILD_PYTHON:-.venv/bin/python}"
BASE_PYTHON="${BASE_PYTHON:-python3}"
OUT="evidence/packaging"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

stamp() { date '+%Y-%m-%d %H:%M %Z'; }

rm -rf dist build
{
  echo "# $(stamp) — $BUILD_PYTHON -m build"
  "$BUILD_PYTHON" -m build 2>&1 | grep -E '^(\* |Successfully|ERROR|error)' || true
} > "$OUT/build.txt"
ls dist/*.whl dist/*.tar.gz > /dev/null

{
  echo "# $BUILD_PYTHON -m twine check --strict dist/*   ($("$BUILD_PYTHON" -m twine --version | head -1 | cut -d'(' -f1))"
  "$BUILD_PYTHON" -m twine check --strict dist/* 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
} > "$OUT/twine_check.txt"
if command -v sha256sum > /dev/null; then
  sha256sum dist/* | sed 's|  | |' > "$OUT/dist_sha256.txt"
else
  shasum -a 256 dist/* | sed 's|  | |' > "$OUT/dist_sha256.txt"
fi

WHEEL="$(ls dist/*.whl)"
"$BUILD_PYTHON" - "$WHEEL" > "$OUT/wheel_contents.txt" <<'PY'
import email
import sys
import zipfile

wheel = zipfile.ZipFile(sys.argv[1])
names = wheel.namelist()
meta = email.message_from_bytes(
    wheel.read(next(name for name in names if name.endswith(".dist-info/METADATA")))
)
print(f"# wheel: {sys.argv[1]}")
print("files:", len(names))
print("py.typed present:", any(n.endswith("backtest_auditor/py.typed") for n in names))
print("bundled JSON schemas:", sum(n.endswith(".schema.json") for n in names))
for key in ("Name", "Version", "Requires-Python", "License", "License-Expression"):
    print(f"{key}:", meta.get(key))
print("Provides-Extra:", ", ".join(meta.get_all("Provides-Extra") or []))
print("Classifiers:")
for item in meta.get_all("Classifier") or []:
    print("  ", item)
print("Requires-Dist:")
for item in meta.get_all("Requires-Dist") or []:
    print("  ", item)
PY

VENV="$WORK/venv"
"$BASE_PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
{
  echo "# $(stamp) — clean venv from $("$BASE_PYTHON" --version 2>&1); pip install $WHEEL"
  "$VENV/bin/pip" install "$WHEEL" 2>&1 | tail -1
  echo "# pip check"
  "$VENV/bin/pip" check
  echo "# pip freeze"
  "$VENV/bin/pip" freeze | sed 's|@ file://.*|@ <the wheel>|'
} > "$OUT/wheel_install.txt"

RUN="$WORK/run"
mkdir -p "$RUN"
cp examples/quickstart/audit_returns.csv "$RUN/"
EXAMPLE="$ROOT/examples/v1_5i_implementation_risk"
(
  cd "$RUN"
  echo "# cwd: a temporary directory outside the checkout; console script from the clean venv"
  "$VENV/bin/python" -c 'import backtest_auditor, sys; print(backtest_auditor.__file__.replace(sys.prefix, "<venv>"), backtest_auditor.__version__)'
  echo
  echo "# quickstart step 1 (docs/getting-started.md)"
  "$VENV/bin/backtest-auditor" audit_returns.csv --run-id quickstart \
    --declared-frequency B --periods-per-year 252 \
    --audit-id quickstart --audit-timestamp 2026-11-02T09:00:00Z \
    --git-commit synthetic-example --format markdown --output report.md
  echo "exit $? — report.md has $(wc -l < report.md | tr -d ' ') lines"
  grep -E '^\| [a-z_]+ \| (supported_under_stated_assumptions|insufficient_evidence|fragile|ineligible|unsupported|contradicted)' report.md | cut -d'|' -f2-3
  echo
  echo "# quickstart step 2 (statistical evidence configured)"
  "$VENV/bin/backtest-auditor" audit_returns.csv --run-id quickstart \
    --declared-frequency B --periods-per-year 252 \
    --annual-risk-free-rate 0.0 --benchmark-annualized-sharpe-ratio 0.0 \
    --required-psr-confidence-level 0.95 \
    --serial-max-lag 10 --serial-significance-level 0.05 \
    --hac-max-lag 10 --hac-kernel bartlett \
    --bootstrap-method stationary --bootstrap-interval-method percentile \
    --bootstrap-replications 2000 --bootstrap-confidence-level 0.95 \
    --bootstrap-block-length 5 --bootstrap-seed 7 \
    --audit-id quickstart --audit-timestamp 2026-11-02T09:00:00Z \
    --git-commit synthetic-example --format markdown --output report.md
  echo "exit $?"
  grep -E '^\| [a-z_]+ \| (supported_under_stated_assumptions|insufficient_evidence|fragile|ineligible|unsupported|contradicted)' report.md | cut -d'|' -f2-3
  grep -E '^\| (Annualized Sharpe ratio|Probabilistic Sharpe Ratio) ' report.md | sort -u
  echo
  echo "# implementation-risk CLI on examples/v1_5i_implementation_risk"
  "$VENV/bin/backtest-auditor" implementation-risk \
    "$EXAMPLE/reference-bundle.zip" "$EXAMPLE/candidate-bundle.zip" \
    --normalization-plan "$EXAMPLE/normalization-plan.json" \
    --comparison-policy "$EXAMPLE/comparison-policy.json" \
    --measurement-policy "$EXAMPLE/measurement-policy.json" \
    --assessment-policy "$EXAMPLE/assessment-policy.json" \
    --audit-id v1-5i-example-audit --audit-timestamp 2026-08-21T12:00:00Z \
    --git-commit v1.5.0-example --format json --output implementation-risk.json
  echo "exit $?"
  "$VENV/bin/python" - "$EXAMPLE/implementation-risk-report.json" <<'PY'
import json
import sys

fresh = json.load(open("implementation-risk.json"))
committed = json.load(open(sys.argv[1]))
ENVIRONMENT = {"package_version", "platform_machine", "platform_system",
               "python_version", "manifest_sha256", "dependency_versions"}

def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in ENVIRONMENT}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value

print("schema_version:", fresh["schema_version"])
same = strip(fresh) == strip(committed)
print("equal to the committed example report, environment fields aside:", same)
PY
) > "$OUT/wheel_quickstart.txt" 2>&1

"$VENV/bin/pip" freeze | grep -v '^backtest-integrity-auditor' > "$WORK/runtime.txt"
{
  echo "# runtime dependencies resolved by the clean venv:"
  cat "$WORK/runtime.txt"
  echo "# $(stamp) — pip-audit -r <that list> --no-deps --disable-pip"
  "$BUILD_PYTHON" -m pip_audit -r "$WORK/runtime.txt" --no-deps --disable-pip \
    --progress-spinner off 2>&1 | grep -v '^WARNING' || true
} > "$OUT/pip_audit_runtime.txt"

echo "package check complete; see $OUT/"
