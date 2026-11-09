"""V1.5 identities named in SPEC 3 and SPEC 7 (package bumped to 1.5.1 for W1-J2, 1.5.2 for W2-J6): report schema 2.5,
manifest schema 1.1, canonical artifact bundle schema 1.0, and the five engine
adapters.

Night-3 ran against 1.0.0 and recorded these as absent (F11), with two skipped
placeholders. On 1.5.0 the placeholders have real targets: the bundle and
adapter contract tests are in test_v15_bundle_and_adapters.py. The night-3 test
that asserted the bundle modules were *not* importable checked module names
that never existed (the real ones live under implementation_risk), so it is
replaced by the positive import test below.

Night 7's rewrite of night 3's test_v15_contracts.py, carried from night/import-1.5.0
beside night 3's original (which the spec names and which is kept unchanged)
because it checks more: the four contract versions, `__version__` (night 7's V1,
which 1.5.1 fixes) and positive imports. Only the expected package version
changed, 1.5.0 -> 1.5.1 -> 1.5.2.
"""

import importlib

import pytest

import backtest_auditor
from backtest_auditor.application.run_manifest import RUN_MANIFEST_SCHEMA_VERSION
from backtest_auditor.implementation_risk.adapters.canonical_bundle import (
    BUNDLE_SCHEMA_VERSION,
)


def test_package_and_schema_versions_are_the_ones_the_spec_names():
    found = (
        backtest_auditor.PACKAGE_VERSION,
        backtest_auditor.REPORT_SCHEMA_VERSION,
        RUN_MANIFEST_SCHEMA_VERSION,
        BUNDLE_SCHEMA_VERSION,
    )
    assert found == ("1.6.0", "2.5", "1.1", "1.0"), (
        f"spec names package 1.6.0 / report 2.5 / manifest 1.1 / bundle 1.0; found {found}"
    )


def test_dunder_version_matches_the_package_version():
    """Finding V1 (Low): SPEC 7 expects `__version__`; 1.5.0 defined only
    PACKAGE_VERSION. 1.5.1 adds `__version__ = PACKAGE_VERSION`."""
    assert (
        getattr(backtest_auditor, "__version__", None)
        == backtest_auditor.PACKAGE_VERSION
    )


@pytest.mark.parametrize(
    "name",
    [
        "backtest_auditor.implementation_risk",
        "backtest_auditor.implementation_risk.adapters.canonical_bundle",
        "backtest_auditor.implementation_risk.adapters.vectorbt",
        "backtest_auditor.implementation_risk.adapters.bt",
        "backtest_auditor.implementation_risk.adapters.backtrader",
        "backtest_auditor.implementation_risk.adapters.quantconnect_lean",
        "backtest_auditor.implementation_risk.adapters.nautilustrader",
    ],
)
def test_v15_bundle_writer_and_adapters_import_without_engine_packages(name):
    importlib.import_module(name)
