"""Write every generated block the documentation quotes, and check it is current.

* ``quickstart/`` and ``readme/``: runs the audit commands of
  docs/getting-started.md and of the README example and keeps their real
  output (README.md must contain the ``readme/`` blocks verbatim);
* ``adapters/``: one evidence-level table per engine adapter, read from the
  adapter's own capability declaration;
* ``notebooks/``: the cells of examples/notebooks/*.ipynb tagged ``doc:<name>``
  and their printed output, quoted verbatim by the how-to guides. These are
  read from the committed notebooks, not re-executed: run
  examples/notebooks/run_notebooks.sh for that.

The pages include these files with pymdownx.snippets, so no block they include
is typed by hand (a few install and copy commands in the prose are):

    python scripts/docs_snippets.py           # regenerate the snippets
    python scripts/docs_snippets.py --check   # fail if a fresh run differs

The commands run in a temporary directory against the ``backtest-auditor``
console script installed next to the running interpreter. Only report lines
that do not depend on the machine are kept (no Python, platform or dependency
versions), so ``--check`` is meant to pass on any supported environment with
the same package version; it has been run on macOS arm64 with Python 3.13.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNIPPETS = ROOT / "docs" / "snippets"
NOTEBOOKS = ROOT / "examples" / "notebooks"
INPUT = ROOT / "examples" / "quickstart" / "audit_returns.csv"
CLI = Path(sys.executable).with_name("backtest-auditor")

IDENTITY = [
    "--audit-id", "quickstart",
    "--audit-timestamp", "2026-11-02T09:00:00Z",
    "--git-commit", "synthetic-example",
]  # fmt: skip
STEP1 = [
    "backtest-auditor", "audit_returns.csv",
    "--run-id", "quickstart",
    "--declared-frequency", "B",
    "--periods-per-year", "252",
    *IDENTITY,
    "--format", "markdown",
    "--output", "report.md",
]  # fmt: skip
STATISTICS = [
    "--annual-risk-free-rate", "0.0",
    "--benchmark-annualized-sharpe-ratio", "0.0",
    "--required-psr-confidence-level", "0.95",
    "--serial-max-lag", "10",
    "--serial-significance-level", "0.05",
    "--hac-max-lag", "10",
    "--hac-kernel", "bartlett",
    "--bootstrap-method", "stationary",
    "--bootstrap-interval-method", "percentile",
    "--bootstrap-replications", "2000",
    "--bootstrap-confidence-level", "0.95",
    "--bootstrap-block-length", "5",
    "--bootstrap-seed", "7",
]  # fmt: skip
STEP2 = [*STEP1[:8], *STATISTICS, *STEP1[8:]]
README = ROOT / "README.md"
README_STEP = [
    "backtest-auditor", "examples/quickstart/audit_returns.csv",
    "--run-id", "quickstart",
    "--declared-frequency", "B",
    "--periods-per-year", "252",
    "--annual-risk-free-rate", "0.0",
    "--benchmark-annualized-sharpe-ratio", "0.0",
    "--required-psr-confidence-level", "0.95",
    "--format", "markdown",
    "--output", "report.md",
]  # fmt: skip
STEP3 = [*STEP2[:-4], "--format", "json", "--output", "report.json"]


def shell_text(argv: list[str]) -> str:
    """The command as a reader types it, one option (and its value) per line."""

    head, rest = argv[:2], argv[2:]
    lines = [" ".join(head)]
    index = 0
    while index < len(rest):
        if index + 1 < len(rest) and not rest[index + 1].startswith("--"):
            lines.append(f"  {rest[index]} {shlex.quote(rest[index + 1])}")
            index += 2
        else:
            lines.append(f"  {rest[index]}")
            index += 1
    return " \\\n".join(lines) + "\n"


def run(argv: list[str], cwd: Path) -> None:
    command = [str(CLI), *argv[1:]] if argv[0] == "backtest-auditor" else argv
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if completed.returncode != 0 or completed.stdout or completed.stderr:
        raise SystemExit(
            f"{shlex.join(argv)} exited {completed.returncode}\n"
            f"{completed.stdout}{completed.stderr}"
        )


def section(report: str, heading: str) -> list[str]:
    """The lines of one ``## heading`` section, without the heading."""

    lines = report.splitlines()
    start = lines.index(f"## {heading}") + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return list(lines[start:end])


def table(lines: list[str], *, keep: tuple[str, ...] | None = None) -> str:
    """The first Markdown table in ``lines``, optionally only the named columns."""

    start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    end = next(
        (i for i in range(start, len(lines)) if not lines[i].startswith("|")),
        len(lines),
    )
    block = lines[start:end]
    if keep is not None:
        names = [cell.strip() for cell in block[0].strip("|").split("|")]
        index = [names.index(name) for name in keep]
        block = [
            "| "
            + " | ".join(row.strip("|").split("|")[i].strip() for i in index)
            + " |"
            for row in block
        ]
    return "\n".join(block) + "\n"


def rows(
    lines: list[str],
    names: tuple[str, ...],
    *,
    header: str = "| Metric | Value |",
    columns: int | None = None,
) -> str:
    """Header, separator and the named rows of the table that starts ``header``."""

    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = next(
        (i for i in range(start, len(lines)) if not lines[i].startswith("|")),
        len(lines),
    )
    block = lines[start:end]
    keep = block[:2] + [row for row in block[2:] if row.split("|")[1].strip() in names]
    missing = set(names) - {row.split("|")[1].strip() for row in keep[2:]}
    if missing:
        raise SystemExit(f"rows not found under {header!r}: {sorted(missing)}")
    if columns is not None:
        keep = ["|".join(row.split("|")[: columns + 1]) + "|" for row in keep]
    return "\n".join(keep) + "\n"


def validate_against_public_schema(document: dict) -> None:
    """Raise unless ``document`` is a valid single-run report schema 2.5."""

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from backtest_auditor.reporting.schema_catalog import (
        PUBLIC_SCHEMA_FILES,
        load_public_schema,
    )

    schemas = [load_public_schema(name) for name in PUBLIC_SCHEMA_FILES]
    registry = Registry().with_resources(
        [(schema["$id"], Resource.from_contents(schema)) for schema in schemas]
    )
    Draft202012Validator(
        load_public_schema("single_run_report_2_5"), registry=registry
    ).validate(document)


def quickstart(directory: Path) -> dict[str, str]:
    shutil.copy(INPUT, directory / "audit_returns.csv")
    out: dict[str, str] = {}
    head = (directory / "audit_returns.csv").read_text().splitlines()[:4]
    out["head.txt"] = "$ head -n 4 audit_returns.csv\n" + "\n".join(head) + "\n"
    version = subprocess.run(
        [sys.executable, "-c", "import backtest_auditor as b; print(b.__version__)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    out["version.txt"] = (
        '$ python -c "import backtest_auditor as b; print(b.__version__)"\n' + version
    )

    run(STEP1, directory)
    report = (directory / "report.md").read_text(encoding="utf-8")
    out["step1.cmd.txt"] = shell_text(STEP1)
    out["step1.profile.txt"] = table(
        section(report, "Dimensioned evidence profile"),
        keep=("Dimension", "Status", "Summary"),
    )
    out["step1.findings.txt"] = table(
        section(report, "Findings"), keep=("Code", "Remediation")
    )
    out["step1.manifest.txt"] = rows(
        section(report, "Audit-run manifest"),
        header="| Property | Value |",
        names=(
            "Audit ID",
            "Audit timestamp UTC",
            "Package version",
            "Report schema",
            "Git commit",
            "Normalized-data SHA-256",
            "Configuration SHA-256",
        ),
    )
    out["step1.raw.txt"] = rows(
        section(report, "Audit-run manifest"),
        ("strategy_returns",),
        header="| Role | File |",
    )
    out["step1.annualized.txt"] = rows(
        section(report, "Annualized statistics"),
        (
            "Annualized arithmetic mean return",
            "Annualized sample volatility",
            "Annualized Sharpe ratio",
        ),
    )
    out["step1.lines.txt"] = f"{len(report.splitlines())}\n"

    run(STEP2, directory)
    report = (directory / "report.md").read_text(encoding="utf-8")
    out["step2.cmd.txt"] = shell_text(STEP2)
    out["step2.profile.txt"] = table(
        section(report, "Dimensioned evidence profile"),
        keep=("Dimension", "Status", "Summary"),
    )
    out["step2.psr.txt"] = rows(
        section(report, "Sharpe uncertainty and PSR"),
        (
            "Annualized Sharpe ratio",
            "Annualized Sharpe standard error",
            "Probabilistic Sharpe Ratio",
        ),
    )
    out["step2.mintrl.txt"] = rows(
        section(report, "Minimum track-record length"),
        (
            "Observation count",
            "Required PSR confidence level",
            "Confidence requirement met",
            "Minimum required whole observations",
            "Equivalent track-record length (years)",
        ),
    )
    out["step2.bootstrap.txt"] = rows(
        section(report, "Bootstrap confidence intervals"),
        ("iid_annualized_sharpe_ratio", "hac_adjusted_annualized_sharpe_ratio"),
        header="| Metric | Status |",
        columns=5,
    )
    out["step2.serial.txt"] = rows(
        section(report, "Serial-dependence diagnostics"),
        (
            "Ljung-Box statistic",
            "p-value",
            "Serial dependence detected",
            "Runs dependence detected",
        ),
    )

    run(STEP3, directory)
    document = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    validate_against_public_schema(document)
    out["step3.cmd.txt"] = shell_text(STEP3)
    profile = document["evidence_profile"]["dimensions"]
    out["step3.json.txt"] = (
        json.dumps(
            {
                "schema_version": document["schema_version"],
                "audit_type": document["audit_type"],
                "evidence_profile": {
                    item["dimension"]: item["status"] for item in profile
                },
            },
            indent=2,
        )
        + "\n"
    )
    return {f"quickstart/{name}": text for name, text in out.items()}


def adapter_tables() -> dict[str, str]:
    """Evidence levels per adapter, from each adapter's capability declaration."""

    from backtest_auditor.implementation_risk import (
        BACKTRADER_DESCRIPTOR,
        BT_DESCRIPTOR,
        NAUTILUSTRADER_DESCRIPTOR,
        QUANTCONNECT_LEAN_DESCRIPTOR,
        VECTORBT_DESCRIPTOR,
    )

    out = {}
    for name, descriptor in (
        ("vectorbt", VECTORBT_DESCRIPTOR),
        ("bt", BT_DESCRIPTOR),
        ("backtrader", BACKTRADER_DESCRIPTOR),
        ("nautilustrader", NAUTILUSTRADER_DESCRIPTOR),
        ("quantconnect_lean", QUANTCONNECT_LEAN_DESCRIPTOR),
    ):
        lines = [
            f"Adapter `{descriptor.adapter_id}` {descriptor.adapter_version}, "
            f"tested engine versions: "
            f"{', '.join(descriptor.tested_engine_versions)}.",
            "",
            "| Level | Availability | Origin | Adapter's explanation |",
            "|---|---|---|---|",
        ]
        for capability in descriptor.capabilities:
            lines.append(
                f"| `{capability.level.value}` | {capability.availability.value} "
                f"| {capability.origin.value} | {capability.explanation} |"
            )
        out[f"adapters/{name}.levels.md"] = "\n".join(lines) + "\n"
    return out


def notebook_cells() -> dict[str, str]:
    """Code cells tagged ``doc:<name>``, and the export cell's printed warnings."""

    out = {}
    for path in sorted(NOTEBOOKS.glob("*.ipynb")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for cell in document["cells"]:
            tags = [
                tag[4:]
                for tag in cell.get("metadata", {}).get("tags", [])
                if tag.startswith("doc:")
            ]
            for tag in tags:
                source = "".join(cell["source"]).rstrip("\n") + "\n"
                out[f"notebooks/{path.stem}/{tag}.py"] = source
                printed = "".join(
                    "".join(output["text"])
                    for output in cell.get("outputs", [])
                    if output["output_type"] == "stream"
                )
                if tag == "export":
                    warnings = [
                        line
                        for line in printed.splitlines()
                        if line.startswith("adapter warnings:")
                    ]
                    if len(warnings) != 1:
                        raise SystemExit(f"{path.name}: export cell was not executed")
                    out[f"notebooks/{path.stem}/warnings.txt"] = warnings[0] + "\n"
    return out


def readme_example(directory: Path) -> dict[str, str]:
    """The README's 60-second example, run from a copy of the repository path."""

    (directory / "examples" / "quickstart").mkdir(parents=True)
    shutil.copy(INPUT, directory / "examples" / "quickstart" / "audit_returns.csv")
    run(README_STEP, directory)
    report = (directory / "report.md").read_text(encoding="utf-8")
    return {
        "readme/command.txt": shell_text(README_STEP),
        "readme/profile.txt": table(
            section(report, "Dimensioned evidence profile"),
            keep=("Dimension", "Status"),
        ),
        "readme/psr.txt": rows(
            section(report, "Minimum track-record length"),
            (
                "Observed Probabilistic Sharpe Ratio",
                "Required PSR confidence level",
                "Minimum required whole observations",
            ),
        ),
    }


def generate(directory: Path) -> dict[str, str]:
    (directory / "quickstart").mkdir()
    (directory / "readme").mkdir()
    return {
        **quickstart(directory / "quickstart"),
        **readme_example(directory / "readme"),
        **adapter_tables(),
        **notebook_cells(),
    }


def readme_is_current(fresh: dict[str, str]) -> list[str]:
    """README.md cannot include snippets, so it must contain them verbatim."""

    text = README.read_text(encoding="utf-8")
    return [
        name for name in fresh if name.startswith("readme/") and fresh[name] not in text
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if not CLI.exists():
        raise SystemExit(f"console script not found next to the interpreter: {CLI}")
    with tempfile.TemporaryDirectory() as temporary:
        fresh = generate(Path(temporary))
    if arguments.check:
        stale = sorted(
            name
            for name, text in fresh.items()
            if not (SNIPPETS / name).exists()
            or (SNIPPETS / name).read_text(encoding="utf-8") != text
        )
        extra = sorted(
            name
            for name in (
                path.relative_to(SNIPPETS).as_posix()
                for path in SNIPPETS.rglob("*")
                if path.is_file()
            )
            if name not in fresh
        )
        readme = readme_is_current(fresh)
        if stale or extra or readme:
            print(
                f"stale snippets: {stale}; unexpected files: {extra}; "
                f"not verbatim in README.md: {readme}"
            )
            return 1
        print(f"{len(fresh)} snippets match a fresh run")
        return 0
    if SNIPPETS.exists():
        shutil.rmtree(SNIPPETS)
    for name, text in fresh.items():
        (SNIPPETS / name).parent.mkdir(parents=True, exist_ok=True)
        (SNIPPETS / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(fresh)} snippets to {SNIPPETS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
