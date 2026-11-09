EXPORTS = kit.OUTPUT / "vectorbt"
exported = export_vectorbt_portfolio(
    portfolio,
    EXPORTS / "export-correct",
    run_id="vectorbt-correct",
    instrument_id=ts.INSTRUMENT,
    base_currency=ts.CURRENCY,
    overwrite=True,
)
adapted = build_v1_5d2_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "vectorbt-correct.zip")
kit.bundle_summary(EXPORTS / "vectorbt-correct.zip")
