"""External representations for canonical implementation-risk evidence."""

from backtest_auditor.implementation_risk.adapters.canonical_bundle import (
    BUNDLE_SCHEMA_VERSION,
    CanonicalArtifactFileBundleAdapter,
    canonical_artifact_bundle_sha256,
)
from backtest_auditor.implementation_risk.adapters.backtrader import (
    BACKTRADER_ADAPTER_ID,
    BACKTRADER_DESCRIPTOR,
    BacktraderArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.bt import (
    BT_ADAPTER_ID,
    BT_DESCRIPTOR,
    BtArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.engine_export import (
    ENGINE_EXPORT_ENVELOPE_FILE,
    EngineExportFileBundleAdapter,
    engine_export_envelope_from_json,
    engine_export_envelope_to_json,
)
from backtest_auditor.implementation_risk.adapters.errors import (
    BundleContractError,
    BundleErrorCode,
)
from backtest_auditor.implementation_risk.adapters.policy_json import (
    MAX_POLICY_JSON_BYTES,
    PolicyContractError,
    comparison_policy_from_json,
    divergence_policy_from_json,
    load_policy_json_file,
    normalization_plan_from_json,
    parse_policy_json,
    parse_policy_json_bytes,
    risk_policy_from_json,
)
from backtest_auditor.implementation_risk.adapters.schema_catalog import (
    CANONICAL_BUNDLE_SCHEMA_FILES,
    load_canonical_bundle_schema,
)
from backtest_auditor.implementation_risk.adapters.vectorbt import (
    VECTORBT_ADAPTER_ID,
    VECTORBT_DESCRIPTOR,
    VectorbtArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.nautilustrader import (
    NAUTILUSTRADER_ADAPTER_ID,
    NAUTILUSTRADER_DESCRIPTOR,
    NautilusTraderArtifactMapper,
)
from backtest_auditor.implementation_risk.adapters.quantconnect_lean import (
    QUANTCONNECT_LEAN_ADAPTER_ID,
    QUANTCONNECT_LEAN_DESCRIPTOR,
    QuantConnectLeanArtifactMapper,
)

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "BACKTRADER_ADAPTER_ID",
    "BACKTRADER_DESCRIPTOR",
    "BT_ADAPTER_ID",
    "BT_DESCRIPTOR",
    "BundleContractError",
    "BundleErrorCode",
    "MAX_POLICY_JSON_BYTES",
    "PolicyContractError",
    "CANONICAL_BUNDLE_SCHEMA_FILES",
    "CanonicalArtifactFileBundleAdapter",
    "ENGINE_EXPORT_ENVELOPE_FILE",
    "EngineExportFileBundleAdapter",
    "BacktraderArtifactMapper",
    "BtArtifactMapper",
    "VECTORBT_ADAPTER_ID",
    "VECTORBT_DESCRIPTOR",
    "VectorbtArtifactMapper",
    "NAUTILUSTRADER_ADAPTER_ID",
    "NAUTILUSTRADER_DESCRIPTOR",
    "NautilusTraderArtifactMapper",
    "QUANTCONNECT_LEAN_ADAPTER_ID",
    "QUANTCONNECT_LEAN_DESCRIPTOR",
    "QuantConnectLeanArtifactMapper",
    "canonical_artifact_bundle_sha256",
    "comparison_policy_from_json",
    "divergence_policy_from_json",
    "engine_export_envelope_from_json",
    "engine_export_envelope_to_json",
    "load_canonical_bundle_schema",
    "load_policy_json_file",
    "normalization_plan_from_json",
    "parse_policy_json",
    "parse_policy_json_bytes",
    "risk_policy_from_json",
]
