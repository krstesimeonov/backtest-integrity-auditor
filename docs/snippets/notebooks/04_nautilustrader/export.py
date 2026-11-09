EXPORTS = kit.OUTPUT / "nautilustrader"


def export_run(engine: BacktestEngine, name: str):
    trader = engine.trader  # a BacktestEngine generates its reports here
    exported = export_nautilustrader_reports(
        trader.generate_orders_report(),
        trader.generate_fills_report(),
        trader.generate_positions_report(),
        trader.generate_account_report(VENUE),
        EXPORTS / f"export-{name}",
        run_id=f"nautilustrader-{name}",
        base_currency=ts.CURRENCY,
        overwrite=True,
    )
    return build_v1_5d3_service().adapt(exported)


engine = run_nautilus(lag=1)
adapted = export_run(engine, "correct")
engine.dispose()
print("adapter warnings:", [warning.code for warning in adapted.warnings])
bundle = kit.write_bundle(adapted.artifacts, EXPORTS / "nautilustrader-correct.zip")
kit.bundle_summary(EXPORTS / "nautilustrader-correct.zip")
