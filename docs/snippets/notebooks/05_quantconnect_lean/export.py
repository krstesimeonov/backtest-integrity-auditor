EXPORTS = kit.OUTPUT / "quantconnect_lean"
result_file, events_file = lean_files(1)
exported = export_quantconnect_lean_results(
    result_file,
    events_file,
    EXPORTS / "export-correct",
    run_id="lean-correct",
    base_currency=ts.CURRENCY,
    engine_version=LEAN_VERSION,
    overwrite=True,
)
adapted = build_v1_5d3_service().adapt(exported)
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "lean-correct.zip")
kit.bundle_summary(EXPORTS / "lean-correct.zip")
