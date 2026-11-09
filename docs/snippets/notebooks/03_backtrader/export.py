EXPORTS = kit.OUTPUT / "backtrader"
exported = export_backtrader_analysis(
    strategy.analyzers.integrity,
    EXPORTS / "export-correct",
    run_id="backtrader-correct",
    base_currency=ts.CURRENCY,
    overwrite=True,
)
adapted = build_v1_5d2_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "backtrader-correct.zip")
kit.bundle_summary(EXPORTS / "backtrader-correct.zip")
