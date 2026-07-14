import pytest
from era100x.data.splits import TemporalSplit, validate_split


def valid() -> TemporalSplit:
    return TemporalSplit(0, 10, 16, 30, 34, 40, purge_ns=6, embargo_ns=4)


def test_valid_split_and_required_purge() -> None:
    validate_split(valid(), max_lookback_ns=2, max_episode_ns=2, max_holding_ns=2)


def test_overlap_purge_and_embargo_fail() -> None:
    with pytest.raises(ValueError, match="purge is below"):
        validate_split(valid(), max_lookback_ns=3, max_episode_ns=3, max_holding_ns=3)
    with pytest.raises(ValueError, match="embargo"):
        validate_split(
            valid().__class__(0, 10, 16, 30, 33, 40, 6, 4),
            max_lookback_ns=2,
            max_episode_ns=2,
            max_holding_ns=2,
        )
