#!/usr/bin/env bash
# Execute the example notebooks in place; their outputs are committed.
#
#   python -m pip install -e . -r requirements-examples.txt   # Python 3.12+
#   bash examples/notebooks/run_notebooks.sh
#
# LEAN_EXPORTER_SRC: the 1.5.2 LEAN exporter cannot read LEAN 2.5's result
# files (`ValueError: order time is ambiguous.`); the fixes are on branch
# wave3/adapter-e2e. Until that branch is merged, set this to a `src`
# directory that contains them; it is put on PYTHONPATH for 05 only, and the
# notebook prints where the package was imported from. Leave it unset after
# the merge.
set -euo pipefail
cd "$(dirname "$0")"
JUPYTER="${JUPYTER:-jupyter}"
# No per-cell timestamps, and one stream output per cell and stream (the kernel
# may split a print into several messages), so re-executing reproduces the files.
EXECUTE=(nbconvert --execute --to notebook --inplace
  --ExecutePreprocessor.record_timing=False --ExecutePreprocessor.coalesce_streams=True)

for notebook in 01_vectorbt 02_bt 03_backtrader 04_nautilustrader; do
  "$JUPYTER" "${EXECUTE[@]}" "$notebook.ipynb"
done

if [ -n "${LEAN_EXPORTER_SRC:-}" ]; then
  PYTHONPATH="$LEAN_EXPORTER_SRC${PYTHONPATH:+:$PYTHONPATH}" \
    "$JUPYTER" "${EXECUTE[@]}" 05_quantconnect_lean.ipynb
else
  "$JUPYTER" "${EXECUTE[@]}" 05_quantconnect_lean.ipynb
fi
