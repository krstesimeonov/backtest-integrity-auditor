"""Show the exporters as they were before W3-J12 failing on real engine output.

Loads the LEAN, NautilusTrader and Backtrader exporters from the branch base
(``21600b3``, i.e. wave1/reconcile-1.5.1) with ``git show`` and runs each on the
same real engine output tests/e2e uses. Run from the repository root:

    .venv/bin/python tests/e2e/show_base_exporters.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
BASE = "21600b3"


def base_exporter(name: str) -> ModuleType:
    source = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "show",
            f"{BASE}:src/backtest_auditor/implementation_risk/exporters/{name}.py",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    path = Path(tempfile.mkdtemp()) / f"base_{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"base_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # Backtrader's metaclass looks it up
    spec.loader.exec_module(module)
    return module


def attempt(label: str, call) -> None:
    try:
        call()
        print(f"{label}: accepted")
    except Exception as error:  # noqa: BLE001 - the point is to show it
        cause = error.__cause__ or error.__context__
        detail = f" (cause: {type(cause).__name__}: {cause})" if cause else ""
        print(f"{label}: {type(error).__name__}: {error}{detail}")


def main() -> None:
    warnings.simplefilter("ignore")
    sys.path.insert(0, str(ROOT / "tests"))
    from backtest_auditor.implementation_risk import build_v1_5d3_service
    from e2e import test_backtrader, test_nautilustrader

    tmp = Path(tempfile.mkdtemp())
    lean = base_exporter("quantconnect_lean")
    data = ROOT / "tests" / "e2e" / "data" / "lean" / "lag1"
    attempt(
        f"LEAN exporter @{BASE} on LEAN's own result files",
        lambda: lean.export_quantconnect_lean_results(
            data / "SynMaCrossAlgorithm.json",
            data / "SynMaCrossAlgorithm-order-events.json",
            tmp / "lean",
            run_id="base",
            base_currency="USD",
            engine_version="2.5.17999",
        ),
    )

    nautilus = base_exporter("nautilustrader")
    engine = test_nautilustrader.run_nautilus(lag=1)
    attempt(
        f"Nautilus exporter @{BASE} on a real BacktestEngine",
        lambda: nautilus.export_nautilustrader_engine(
            engine,
            test_nautilustrader.VENUE,
            tmp / "nautilus",
            run_id="base",
            base_currency="USD",
        ),
    )
    engine.dispose()

    backtrader = base_exporter("backtrader")
    test_backtrader.create_backtrader_audit_analyzer = (
        backtrader.create_backtrader_audit_analyzer
    )
    strategy = test_backtrader.run_backtrader(cheat_on_close=True)

    def backtrader_export_and_adapt() -> None:
        exported = backtrader.export_backtrader_analysis(
            strategy.analyzers.integrity,
            tmp / "backtrader",
            run_id="base",
            base_currency="USD",
        )
        build_v1_5d3_service().adapt(exported)

    attempt(
        f"Backtrader exporter @{BASE}, cheat-on-close run, export + adapt",
        backtrader_export_and_adapt,
    )


if __name__ == "__main__":
    main()
