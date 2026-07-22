from __future__ import annotations

from typing import Any

import pyarrow as pa

from era100x.research.stage_2.baselines.conditional.episode_producer import (
    _load_t10_bindings,
)


class _Reader:
    def read_physical_dataset(self, **kwargs: Any) -> pa.Table:
        if kwargs["dataset_name"] == "price_triggers":
            return pa.Table.from_pylist(
                [
                    {
                        "trigger_id": "shared",
                        "event_parameter_set_id": "P1",
                        "context_state": "UP",
                        "status": "PASS",
                    },
                    {
                        "trigger_id": "shared",
                        "event_parameter_set_id": "P2",
                        "context_state": "DOWN",
                        "status": "REJECTED",
                    },
                ]
            )
        if kwargs["dataset_version"] == "group1-v1-flow-v1":
            return pa.table(
                {
                    "market_episode_id": pa.array([], type=pa.string()),
                    "parameter_set_id": pa.array([], type=pa.string()),
                    "time_combination_id": pa.array([], type=pa.string()),
                    "variant_id": pa.array([], type=pa.string()),
                    "canonical_key_level_id": pa.array([], type=pa.string()),
                    "available_at_ts": pa.array([], type=pa.int64()),
                    "trigger_id": pa.array([], type=pa.string()),
                }
            )
        return pa.Table.from_pylist(
            [
                {
                    "market_episode_id": "episode",
                    "parameter_set_id": "P1",
                    "time_combination_id": "T2",
                    "variant_id": "V1_PRICE",
                    "canonical_key_level_id": "level",
                    "available_at_ts": 10,
                    "trigger_id": "shared",
                }
            ]
        )


def test_episode_context_uses_trigger_and_parameter_composite_key() -> None:
    bindings = _load_t10_bindings(_Reader(), instrument="BTCUSDT")  # type: ignore[arg-type]

    binding = bindings[("episode", "P1", "T2", "V1_PRICE")]
    assert binding["context_state"] == "UP"
    assert binding["trigger_id"] == "shared"
