from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TemporalSplit:
    train_start_ns: int
    train_end_ns: int
    validation_start_ns: int
    validation_end_ns: int
    locked_start_ns: int
    locked_end_ns: int
    purge_ns: int
    embargo_ns: int


def validate_split(
    split: TemporalSplit, *, max_lookback_ns: int, max_episode_ns: int, max_holding_ns: int
) -> None:
    values = (
        split.train_start_ns,
        split.train_end_ns,
        split.validation_start_ns,
        split.validation_end_ns,
        split.locked_start_ns,
        split.locked_end_ns,
    )
    if any(v < 0 for v in values) or not (
        values[0] < values[1] <= values[2] < values[3] <= values[4] < values[5]
    ):
        raise ValueError("time intervals overlap or are empty")
    required = max_lookback_ns + max_episode_ns + max_holding_ns
    if split.purge_ns < required:
        raise ValueError("purge is below required horizon")
    if split.validation_start_ns - split.train_end_ns < split.purge_ns:
        raise ValueError("train-validation purge gap missing")
    if split.locked_start_ns - split.validation_end_ns < split.embargo_ns:
        raise ValueError("locked embargo gap missing")
