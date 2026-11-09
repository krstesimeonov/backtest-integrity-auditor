LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)
reference_bundle = kit.reference_artifacts()
correct = kit.implementation_risk(
    reference_bundle, bundle, LEVELS, name="backtrader-correct"
)
kit.summary(correct)
