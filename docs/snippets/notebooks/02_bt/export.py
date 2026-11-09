EXPORTS = kit.OUTPUT / "bt"
exported = export_bt_result(
    result,
    EXPORTS / "export-correct",
    run_id="bt-correct",
    base_currency=ts.CURRENCY,
    overwrite=True,
)
adapted = build_v1_5d2_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "bt-correct.zip")
kit.bundle_summary(EXPORTS / "bt-correct.zip")
