# V1.5H Evidence-Bounded Risk Assessment

Status: implemented in package `1.5.0a10`.

V1.5H interprets V1.5G divergence through explicit absolute materiality
thresholds, extreme multiples, and family weights. Each observation is
classified as exact-zero, below-threshold, material, or extreme.

The score is bounded from 0 to 100. Each family contributes its declared
weight multiplied by its maximum threshold ratio capped at one. Ratios make
heterogeneous fields comparable only after the operator explicitly supplies
field-specific thresholds; raw values are never summed across units.

Incomplete evidence produces high uncertainty. With the default fail-closed
policy it also withholds the score. Attribution rules report only whether
material source and target families co-occur under complete bilateral evidence.
`supported_cooccurrence` is a hypothesis for investigation, never causal proof.

V1.5H adds no JSON report schema, findings renderer, CLI, Streamlit,
persistence, execution, broker, or live behavior. Those presentation and
integration responsibilities remain V1.5I.
