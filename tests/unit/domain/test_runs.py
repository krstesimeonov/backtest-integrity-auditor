import numpy as np
import pandas as pd
import pytest

from backtest_auditor.domain.enums import ReturnConvention
from backtest_auditor.domain.runs import StrategyRun
from backtest_auditor.domain.series import (
    ReturnSeries,
    SamplingSpec,
)


def test_strategy_run_rejects_empty_run_id() -> None:
    returns = ReturnSeries(
        timestamps=pd.DatetimeIndex(["2026-01-01"]),
        values=np.array([0.01]),
        convention=ReturnConvention.SIMPLE,
        sampling=SamplingSpec(),
    )

    with pytest.raises(
        ValueError,
        match="run_id must not be empty",
    ):
        StrategyRun(run_id="   ", returns=returns)
