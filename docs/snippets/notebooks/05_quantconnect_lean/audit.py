LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)
reference_bundle = kit.reference_artifacts(
    positions_at="fill", equity_at=lean_equity_instants(1)
)
correct = kit.implementation_risk(reference_bundle, bundle, LEVELS, name="lean-correct")
kit.summary(correct)
