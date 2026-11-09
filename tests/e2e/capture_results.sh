#!/bin/bash
# Captures the command outputs REVIEW.md cites into TEST_RESULTS_E2E.txt.
# Run: bash tests/e2e/capture_results.sh
set -u
cd "$(dirname "$0")/../.."
{
echo "# TEST_RESULTS_E2E.txt — W3-J12, captured $(TZ=Europe/Skopje date '+%Y-%m-%d %H:%M %Z') at $(git rev-parse --short HEAD)"
echo
echo '$ .venv/bin/pytest tests/e2e -q -p no:cacheprovider -W ignore -rxX'
.venv/bin/pytest tests/e2e -q -p no:cacheprovider -W ignore -rxX 2>&1 | tail -6
echo
echo '$ .venv/bin/pytest tests/e2e -p no:cacheprovider -W ignore -v | outcome per test'
.venv/bin/pytest tests/e2e -p no:cacheprovider -W ignore -v 2>&1 | grep -E "PASSED|FAILED|XFAIL|XPASS|ERROR|SKIPPED" | sed -E 's/ +\[ *[0-9]+%\]//'
echo
echo '$ .venv/bin/python -m pytest -q -p no:cacheprovider -W ignore   # whole repository, engines installed'
.venv/bin/python -m pytest -q -p no:cacheprovider -W ignore 2>&1 | tail -1
echo
echo '$ .venv/bin/ruff check src tests scripts benchmarks && .venv/bin/ruff format --check src tests scripts benchmarks'
.venv/bin/ruff check src tests scripts benchmarks 2>&1 | tail -1
.venv/bin/ruff format --check src tests scripts benchmarks 2>&1 | tail -1
echo
echo '$ .venv/bin/mypy src/backtest_auditor/implementation_risk/exporters'
.venv/bin/mypy src/backtest_auditor/implementation_risk/exporters 2>&1 | tail -1
echo
echo '$ .venv/bin/python scripts/generate_v1_5d2_engine_examples.py --check && .venv/bin/python scripts/generate_v1_5d3_engine_examples.py --check'
.venv/bin/python scripts/generate_v1_5d2_engine_examples.py --check && echo "d2 --check ok"
.venv/bin/python scripts/generate_v1_5d3_engine_examples.py --check && echo "d3 --check ok"
echo
echo '$ engine versions'
.venv/bin/python -W ignore -c "import vectorbt, bt, backtrader, nautilus_trader, plotly, numpy, pandas, sys; print('python', sys.version.split()[0], '| vectorbt', vectorbt.__version__, '| bt', bt.__version__, '| backtrader', backtrader.__version__, '| nautilus_trader', nautilus_trader.__version__, '| plotly', plotly.__version__, '| numpy', numpy.__version__, '| pandas', pandas.__version__)"
echo
echo '$ grep End Equity / Total Fees from LEAN own result files (tests/e2e/data/lean)'
for lag in 1 0; do python3 -c "import json,sys; r=json.load(open('tests/e2e/data/lean/lag$lag/SynMaCrossAlgorithm.json')); s=r['statistics']; print('lag$lag', 'End Equity', s['End Equity'], '| Total Orders', s['Total Orders'], '| Total Fees', s['Total Fees'])"; done
echo
echo '$ .venv/bin/python tests/e2e/show_base_exporters.py   # exporters as of 21600b3, on the same real engine output'
.venv/bin/python tests/e2e/show_base_exporters.py 2>&1 | tail -3
echo
echo '$ git log --oneline 21600b3..HEAD'
git log --oneline 21600b3..HEAD
} > TEST_RESULTS_E2E.txt 2>&1
echo "written: $(wc -l < TEST_RESULTS_E2E.txt) lines"
