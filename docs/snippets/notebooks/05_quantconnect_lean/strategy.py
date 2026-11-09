def lean_files(lag: int) -> tuple[Path, Path]:
    folder = Path("data/lean") / f"lag{lag}"
    return (
        folder / "SynMaCrossAlgorithm.json",
        folder / "SynMaCrossAlgorithm-order-events.json",
    )


statistics = json.loads(lean_files(1)[0].read_text(encoding="utf-8"))["statistics"]
{key: statistics[key] for key in ("Total Orders", "End Equity", "Total Fees")}
