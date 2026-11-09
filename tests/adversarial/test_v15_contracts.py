"""V1.5 contracts named in SPEC 3 (package 1.5.0, report schema 2.5, manifest schema 1.1,
canonical artifact bundle schema 1.0, engine adapters). None existed in night 3's
worktree (package 1.0.0, schema 2.4, manifest 1.0; night 3's ASSUMPTIONS.md A1), so
they were skipped with the reason so the morning run showed the gap rather than a
silent pass.

Ported to the 1.5.x line (W1-J2; night 3's F11 is fixed there): the version test
expects the release being cut, 1.6.0 since W7-J07 (1.5.2 from W2-J6, 1.5.1 before; it was a strict
xfail until the 1.5.1 bump landed).
The two placeholders stay skipped: their real counterparts are in
test_v15_bundle_and_adapters.py (night 7). The last test is unchanged and passes
vacuously on 1.5.x: the module names it checks never existed, and the V1.5 bundle
and adapters live under backtest_auditor.implementation_risk.
"""

import importlib

import pytest

import backtest_auditor
from backtest_auditor.application.run_manifest import RUN_MANIFEST_SCHEMA_VERSION


def test_package_and_schema_versions_are_the_ones_the_spec_names():
    assert backtest_auditor.PACKAGE_VERSION == "1.6.0", (
        f"spec names package 1.6.0 / schema 2.5 / manifest 1.1; worktree has "
        f"{backtest_auditor.PACKAGE_VERSION} / {backtest_auditor.REPORT_SCHEMA_VERSION} / manifest {RUN_MANIFEST_SCHEMA_VERSION}"
    )


@pytest.mark.skip(
    reason="night-3 placeholder; on 1.5.x see test_v15_bundle_and_adapters.py::test_bundle_writer_cannot_receive_run_missing_required_value"
)
def test_bundle_writer_rejects_missing_required_field():
    pass


@pytest.mark.skip(
    reason="night-3 placeholder; on 1.5.x see test_v15_bundle_and_adapters.py::test_<engine>_adapter_maps_synthetic_run (5 engines)"
)
def test_each_adapter_round_trips_a_synthetic_bundle():
    pass


# Vacuous on 1.5.x (kept unchanged): these names never existed, so the assertion
# holds whether or not V1.5 is present; the real modules are under
# backtest_auditor.implementation_risk and test_v15_bundle_and_adapters.py
# imports them at module level.
def test_no_bundle_or_adapter_module_is_importable():
    for name in (
        "backtest_auditor.bundle",
        "backtest_auditor.adapters",
        "backtest_auditor.artifact_bundle",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)
