"""Generate or verify the deterministic V1.5D1 engine-export example."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from backtest_auditor.implementation_risk import (
    ComparisonLevel,
    EngineExportFileBundleAdapter,
    EngineExportPayload,
    SupportedEngine,
    VerifiedEngineExport,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIRECTORY = ROOT / "examples" / "v1_5d1_engine_export"


def build_example_export() -> VerifiedEngineExport:
    """Build a transport fixture, not a concrete vectorbt mapper fixture."""

    return VerifiedEngineExport.create(
        run_id="example-vectorbt-export",
        engine=SupportedEngine.VECTORBT,
        engine_version="example-only",
        export_format_id="backtest-auditor.vectorbt",
        export_format_version="1.0",
        declared_levels=(ComparisonLevel.RETURN,),
        payloads=(
            EngineExportPayload(
                path="returns.csv",
                role="returns",
                media_type="text/csv; charset=utf-8",
                data=(
                    b"timestamp,return\n"
                    b"2026-01-02T00:00:00Z,0.01\n"
                    b"2026-01-05T00:00:00Z,-0.005\n"
                ),
            ),
        ),
    )


def _same_tree(left: Path, right: Path) -> bool:
    left_files = tuple(
        item.relative_to(left) for item in sorted(left.rglob("*")) if item.is_file()
    )
    right_files = tuple(
        item.relative_to(right) for item in sorted(right.rglob("*")) if item.is_file()
    )
    return left_files == right_files and all(
        (left / name).read_bytes() == (right / name).read_bytes() for name in left_files
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    adapter = EngineExportFileBundleAdapter()
    export = build_example_export()
    if arguments.check:
        with tempfile.TemporaryDirectory() as temporary:
            generated = adapter.write(export, Path(temporary) / "example")
            if not EXAMPLE_DIRECTORY.is_dir() or not _same_tree(
                generated,
                EXAMPLE_DIRECTORY,
            ):
                raise SystemExit("V1.5D1 example differs from deterministic generator")
        return
    adapter.write(export, EXAMPLE_DIRECTORY, overwrite=EXAMPLE_DIRECTORY.exists())


if __name__ == "__main__":
    main()
