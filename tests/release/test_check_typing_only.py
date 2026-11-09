"""scripts/check_typing_only.py tells docstring/typing edits from logic edits."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_typing_only import typing_only

BASE = """\
import math
from statistics import NormalDist


def ratio(values, scale=2):
    common = {"count": len(values), "scale": scale}
    return _result(**common) / math.sqrt(scale)


class Result:
    total: float
"""


@pytest.mark.parametrize(
    "edited",
    [
        # docstrings on module, function and class
        '"""Module."""\n'
        + BASE.replace(
            "def ratio(values, scale=2):\n",
            'def ratio(values, scale=2):\n    """Ratio."""\n',
        ),
        # argument, return and variable annotations, plus an import they need
        "from typing import Any\n"
        + BASE.replace(
            "def ratio(values, scale=2):",
            "def ratio(values: list[float], scale: int = 2) -> float:",
        ).replace("common = {", "common: dict[str, Any] = {"),
        # an annotation-only name added to an existing import
        BASE.replace(
            "from statistics import NormalDist",
            "from statistics import NormalDist, StatisticsError",
        ).replace("def ratio(values,", "def ratio(values: StatisticsError,"),
        # a new TYPE_CHECKING block
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import numpy\n"
        + BASE,
        # a bare annotation on a name the function assigns anyway
        BASE.replace("    common = {", "    common: dict\n    common = {"),
    ],
)
def test_docstring_and_typing_edits_are_typing_only(edited: str) -> None:
    assert typing_only(BASE, edited)


@pytest.mark.parametrize(
    "edited",
    [
        BASE.replace("scale=2", "scale=3"),
        BASE.replace("math.sqrt(scale)", "math.sqrt(scale + 1)"),
        BASE.replace("common", "shared"),
        BASE.replace('"count": len(values), ', ""),
        "import os\nos.environ\n" + BASE,
        BASE.replace("    total: float\n", "    total: float = 0.0\n"),
        # a new dataclass-style field is a new constructor argument
        BASE.replace("    total: float\n", "    total: float\n    count: int\n"),
        # an import that nothing uses may be a re-export or a side effect
        BASE.replace("from statistics import NormalDist\n", ""),
        "import json\n" + BASE,
        # removing __future__.annotations changes when annotations are evaluated
        "from __future__ import annotations\n" + BASE,
        # a bare annotation on a name the function only reads makes it local
        BASE.replace(
            "    return _result(**common)",
            "    math: object\n    return _result(**common)",
        ),
    ],
)
def test_logic_edits_are_reported(edited: str) -> None:
    assert not typing_only(BASE, edited)


def test_the_else_branch_of_type_checking_is_compared() -> None:
    before = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    pass\nelse:\n    THRESHOLD = 0.05\n"
    )

    assert not typing_only(before, before.replace("0.05", "0.50"))
    assert typing_only(before, before.replace("    pass", "    import numpy"))


def test_one_changed_constant_in_a_real_statistics_module_is_reported() -> None:
    path = Path(__file__).resolve().parents[2] / (
        "src/backtest_auditor/statistics/deflated_sharpe.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "rel_tol=1e-12" in source

    assert typing_only(source, source)
    assert not typing_only(source, source.replace("rel_tol=1e-12", "rel_tol=1e-11", 1))
