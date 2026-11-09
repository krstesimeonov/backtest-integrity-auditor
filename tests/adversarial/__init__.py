"""Adversarial suite (night 3, re-run on 1.5.0 by night 7), run by a plain `pytest`.

This directory is a package so that its module names cannot collide with the
package suite's (tests/unit/statistics also has test_benchmark.py and
test_bootstrap.py). The test modules therefore import the shared builders with
`from .conftest import ...`.
"""
