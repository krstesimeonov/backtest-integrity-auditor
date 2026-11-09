LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.TRADE,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
)
reference_bundle = kit.reference_artifacts(cash=kit.margin_balances())
correct = kit.implementation_risk(
    reference_bundle, bundle, LEVELS, name="nautilustrader-correct"
)
kit.summary(correct)
