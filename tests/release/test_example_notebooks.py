"""The example notebooks are committed executed, top to bottom, without errors.

Re-executing them needs the engine SDKs (requirements-examples.txt and
examples/notebooks/run_notebooks.sh). This test only reads the committed JSON,
so it runs in any environment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest_auditor import PACKAGE_VERSION

NOTEBOOKS = Path(__file__).resolve().parents[2] / "examples" / "notebooks"
ENGINES = {
    "01_vectorbt.ipynb": "vectorbt",
    "02_bt.ipynb": "bt",
    "03_backtrader.ipynb": "backtrader",
    "04_nautilustrader.ipynb": "nautilus_trader",
    "05_quantconnect_lean.ipynb": None,
}
# Notebook 05 needs the wave-3 LEAN exporter fixes, so until they are merged it
# is executed against a temporary merge (examples/notebooks/README.md).
LEAN_SOURCES = ("src/backtest_auditor", "_tmp/rcsim/src/backtest_auditor")


def _cells(name: str) -> list[dict]:
    document = json.loads((NOTEBOOKS / name).read_text(encoding="utf-8"))
    return [cell for cell in document["cells"] if cell["cell_type"] == "code"]


def _stdout(cell: dict) -> str:
    return "".join(
        "".join(output["text"])
        for output in cell["outputs"]
        if output["output_type"] == "stream" and output["name"] == "stdout"
    )


def test_one_notebook_per_adapter() -> None:
    assert {path.name for path in NOTEBOOKS.glob("*.ipynb")} == set(ENGINES)


@pytest.mark.parametrize("name", sorted(ENGINES))
def test_notebook_was_executed_once_in_order_without_errors(name: str) -> None:
    cells = _cells(name)

    assert cells
    assert [cell["execution_count"] for cell in cells] == list(range(1, len(cells) + 1))
    for cell in cells:
        assert not [o for o in cell["outputs"] if o["output_type"] == "error"]
        assert not [
            o
            for o in cell["outputs"]
            if o["output_type"] == "stream" and o["name"] == "stderr"
        ], cell["source"]


@pytest.mark.parametrize("name", sorted(ENGINES))
def test_notebook_names_the_package_it_ran_against(name: str) -> None:
    first = _stdout(_cells(name)[0])
    allowed = LEAN_SOURCES if ENGINES[name] is None else ("src/backtest_auditor",)

    assert any(
        f"backtest_auditor {PACKAGE_VERSION} from {source}\n" in first
        for source in allowed
    ), first
    if ENGINES[name] is not None:
        assert f"{ENGINES[name]} " in first
