import numpy as np
from numpy.typing import NDArray


def stationary_bootstrap_indices(
    observation_count: int,
    *,
    mean_block_length: int,
    rng: np.random.Generator,
) -> NDArray[np.int64]:
    """Draw one circular stationary-bootstrap index path.

    The restart probability is the reciprocal of the declared mean block
    length. The initial index and every restart index are uniform.
    """

    if observation_count <= 0:
        raise ValueError("observation_count must be positive.")
    if mean_block_length <= 0:
        raise ValueError("mean_block_length must be positive.")

    indices = np.empty(observation_count, dtype=np.int64)
    indices[0] = rng.integers(0, observation_count)
    restart_probability = 1.0 / mean_block_length
    for position in range(1, observation_count):
        if rng.random() < restart_probability:
            indices[position] = rng.integers(0, observation_count)
        else:
            indices[position] = (indices[position - 1] + 1) % observation_count
    return indices
