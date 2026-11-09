"""Run the toy strategy in a local QuantConnect LEAN build (no Docker).

Usage::

    python tests/e2e/lean/run_lean.py --lean /path/to/Lean --dotnet /path/to/dotnet

``--lean`` is a LEAN source checkout whose ``Launcher`` has been built
(``dotnet build Launcher/QuantConnect.Lean.Launcher.csproj``); W3-J12 used
commit 278fcb3 (master when 2.5.17999 was published, 2026-08-13) with a
user-local .NET 10 SDK from Microsoft's dotnet-install.sh. The script

1. writes a LEAN data folder for ticker SYN from ``tests/e2e/data/syn_daily.csv``
   (daily zip in deci-cents, identity map and factor files) plus copies of the
   checkout's market-hours and symbol-properties databases, where the US-equity
   calendar has no holidays or early closes (the synthetic market trades every
   weekday);
2. copies ``SynMaCrossAlgorithm.cs`` into the checkout, rebuilds the Launcher;
3. runs the Launcher for lag=1 and lag=0 and copies LEAN's two result files
   (``<algorithm>.json``, ``<algorithm>-order-events.json``) verbatim into
   ``tests/e2e/data/lean/lag1`` and ``lag0``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
E2E = HERE.parent
PRICES = E2E / "data" / "syn_daily.csv"
OUTPUT = E2E / "data" / "lean"
ALGORITHM = "SynMaCrossAlgorithm"


def write_data_folder(lean: Path, data: Path) -> None:
    for name in ("market-hours", "symbol-properties"):
        shutil.copytree(lean / "Data" / name, data / name)
    database_path = data / "market-hours" / "market-hours-database.json"
    database = json.loads(database_path.read_text(encoding="utf-8"))
    # LEAN unions the market-wide holidays into any symbol entry
    # (Common/Util/MarketHoursDatabaseJsonConverter.cs), so a SYN-only entry
    # cannot drop them; this throwaway data folder serves only SYN, so the
    # US-equity calendar itself loses its holidays and early closes.
    entry = database["entries"]["Equity-usa-[*]"]
    for key in ("holidays", "earlyCloses", "lateOpens", "bankHolidays"):
        if key in entry:
            entry[key] = [] if isinstance(entry[key], list) else {}
    database_path.write_text(json.dumps(database, indent=2), encoding="utf-8")

    shutil.copy(PRICES, data / PRICES.name)  # read by the lag=0 (look-ahead) run
    rows = PRICES.read_text(encoding="utf-8").splitlines()[1:]
    lines = []
    for row in rows:
        timestamp, open_, high, low, close, volume = row.split(",")
        day = timestamp[:10].replace("-", "")
        prices = [int(Decimal(item) * 10000) for item in (open_, high, low, close)]
        lines.append(
            f"{day} 00:00,{prices[0]},{prices[1]},{prices[2]},{prices[3]},{volume}"
        )
    daily = data / "equity" / "usa" / "daily"
    daily.mkdir(parents=True)
    with zipfile.ZipFile(daily / "syn.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("syn.csv", "\n".join(lines) + "\n")
    for kind, text in (
        ("map_files", "19980102,syn,Q\n20501231,syn,Q\n"),
        ("factor_files", "19980102,1,1,1\n20501231,1,1,0\n"),
    ):
        folder = data / "equity" / "usa" / kind
        folder.mkdir(parents=True)
        (folder / "syn.csv").write_text(text, encoding="utf-8")


def build(lean: Path, dotnet: Path) -> None:
    shutil.copy(HERE / f"{ALGORITHM}.cs", lean / "Algorithm.CSharp" / f"{ALGORITHM}.cs")
    subprocess.run(
        [
            str(dotnet),
            "build",
            "Launcher/QuantConnect.Lean.Launcher.csproj",
            "-c",
            "Debug",
            "-v",
            "q",
        ],
        cwd=lean,
        check=True,
    )


def _strip_comments(text: str) -> str:
    """Drop the ``//`` comments LEAN's config.json carries, outside strings."""

    out = []
    in_string = escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("//", index):
            while index < len(text) and text[index] != "\n":
                index += 1
            continue
        else:
            out.append(char)
        index += 1
    return "".join(out)


def run(lean: Path, dotnet: Path, data: Path, lag: int, workspace: Path) -> Path:
    launcher = lean / "Launcher" / "bin" / "Debug"
    config = json.loads(_strip_comments((launcher / "config.json").read_text("utf-8")))
    results = workspace / f"results-lag{lag}"
    results.mkdir()
    config.update(
        {
            "environment": "backtesting",
            "algorithm-type-name": ALGORITHM,
            "algorithm-language": "CSharp",
            "algorithm-location": "QuantConnect.Algorithm.CSharp.dll",
            "data-folder": str(data) + "/",
            "results-destination-folder": str(results),
            "close-automatically": True,
            "debugging": False,
            "parameters": {"lag": str(lag), "peek-file": PRICES.name},
        }
    )
    config_path = workspace / f"config-lag{lag}.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log = workspace / f"lean-lag{lag}.log"
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(
            [
                str(dotnet),
                "QuantConnect.Lean.Launcher.dll",
                "--config",
                str(config_path),
            ],
            cwd=launcher,
            check=True,
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=900,
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lean", type=Path, required=True)
    parser.add_argument("--dotnet", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--skip-build", action="store_true")
    arguments = parser.parse_args()
    workspace = arguments.workspace or Path(tempfile.mkdtemp(prefix="lean-e2e-"))
    workspace.mkdir(parents=True, exist_ok=True)
    data = workspace / "data"
    write_data_folder(arguments.lean, data)
    if not arguments.skip_build:
        build(arguments.lean, arguments.dotnet)
    for lag in (1, 0):
        results = run(arguments.lean, arguments.dotnet, data, lag, workspace)
        destination = OUTPUT / f"lag{lag}"
        destination.mkdir(parents=True, exist_ok=True)
        for suffix in (".json", "-order-events.json"):
            shutil.copy(
                results / f"{ALGORITHM}{suffix}", destination / f"{ALGORITHM}{suffix}"
            )
        print(f"lag={lag}: {destination}")
    print(f"workspace: {workspace}")


if __name__ == "__main__":
    main()
