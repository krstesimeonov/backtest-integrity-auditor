LEVELS = (
    ComparisonLevel.FILL,
    ComparisonLevel.POSITION,
    ComparisonLevel.CASH,
    ComparisonLevel.COST,
    ComparisonLevel.EQUITY,
    ComparisonLevel.RETURN,
)
reference_bundle = kit.reference_artifacts(
    prestart=prices.index[0] - pd.DateOffset(days=1)
)
correct = kit.implementation_risk(reference_bundle, bundle, LEVELS, name="bt-correct")
kit.summary(correct)
