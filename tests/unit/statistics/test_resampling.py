import numpy as np
import pytest

from backtest_auditor.statistics.resampling import stationary_bootstrap_indices


def test_stationary_bootstrap_is_seeded_bounded_and_circular() -> None:
    first = stationary_bootstrap_indices(
        8, mean_block_length=4, rng=np.random.default_rng(42)
    )
    second = stationary_bootstrap_indices(
        8, mean_block_length=4, rng=np.random.default_rng(42)
    )

    assert np.array_equal(first, second)
    assert first.tolist() == [0, 1, 2, 3, 6, 7, 0, 1]
    assert np.all((first >= 0) & (first < 8))


@pytest.mark.parametrize(
    ("count", "block", "message"),
    [(0, 1, "observation_count"), (2, 0, "mean_block_length")],
)
def test_stationary_bootstrap_rejects_invalid_dimensions(
    count: int, block: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        stationary_bootstrap_indices(
            count, mean_block_length=block, rng=np.random.default_rng(1)
        )
