"""Registers the marker of the slow known-truth scenarios (about 6.5 minutes).

They run by default; skip them with ``-m "not edge_audit_calibration"``.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "edge_audit_calibration: V4 known-truth scenarios over hundreds of seeds",
    )
