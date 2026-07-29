"""Reusable immutable range-extrema index for T11 lifecycle paths."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DecimalTimeRangeIndex:
    timestamps_ns: tuple[int, ...]
    values: tuple[Decimal, ...]
    _tree_size: int
    _minimum_tree: tuple[Decimal, ...]
    _maximum_tree: tuple[Decimal, ...]

    @classmethod
    def build(
        cls,
        timestamps_ns: tuple[int, ...],
        values: tuple[Decimal, ...],
    ) -> DecimalTimeRangeIndex:
        if len(timestamps_ns) != len(values) or not values:
            raise ValueError("range index requires aligned non-empty columns")
        if any(right < left for left, right in zip(timestamps_ns, timestamps_ns[1:], strict=False)):
            raise ValueError("range index timestamps must be increasing")
        if any(value <= 0 for value in values):
            raise ValueError("range index prices must be positive")
        size = 1
        while size < len(values):
            size *= 2
        positive_infinity = Decimal("Infinity")
        negative_infinity = Decimal("-Infinity")
        minimum = [positive_infinity] * (2 * size)
        maximum = [negative_infinity] * (2 * size)
        for index, value in enumerate(values):
            minimum[size + index] = value
            maximum[size + index] = value
        for node in range(size - 1, 0, -1):
            minimum[node] = min(minimum[node * 2], minimum[node * 2 + 1])
            maximum[node] = max(maximum[node * 2], maximum[node * 2 + 1])
        return cls(
            timestamps_ns=timestamps_ns,
            values=values,
            _tree_size=size,
            _minimum_tree=tuple(minimum),
            _maximum_tree=tuple(maximum),
        )

    def bounds(self, start_ns: int, end_ns: int) -> tuple[int, int]:
        if end_ns <= start_ns:
            raise ValueError("range query must be non-empty")
        return (
            bisect_left(self.timestamps_ns, start_ns),
            bisect_left(self.timestamps_ns, end_ns),
        )

    def last_at_or_before(self, timestamp_ns: int) -> tuple[int, Decimal] | None:
        index = bisect_right(self.timestamps_ns, timestamp_ns) - 1
        if index < 0:
            return None
        return self.timestamps_ns[index], self.values[index]

    def range_max(self, start_ns: int, end_ns: int) -> tuple[int, Decimal] | None:
        left, right = self.bounds(start_ns, end_ns)
        if left == right:
            return None
        best_index = self._first_extreme_index(
            left=left,
            right=right,
            threshold=self._range_max_value(left, right),
            use_maximum=True,
        )
        if best_index is None:
            raise AssertionError("non-empty range lost its maximum")
        return self.timestamps_ns[best_index], self.values[best_index]

    def first_ge(
        self, start_ns: int, end_ns: int, threshold: Decimal
    ) -> tuple[int, Decimal, int] | None:
        left, right = self.bounds(start_ns, end_ns)
        index = self._first_extreme_index(
            left=left,
            right=right,
            threshold=threshold,
            use_maximum=True,
        )
        if index is None:
            return None
        return self.timestamps_ns[index], self.values[index], index

    def first_le(
        self, start_ns: int, end_ns: int, threshold: Decimal
    ) -> tuple[int, Decimal, int] | None:
        left, right = self.bounds(start_ns, end_ns)
        index = self._first_extreme_index(
            left=left,
            right=right,
            threshold=threshold,
            use_maximum=False,
        )
        if index is None:
            return None
        return self.timestamps_ns[index], self.values[index], index

    def _range_max_value(self, left: int, right: int) -> Decimal:
        left += self._tree_size
        right += self._tree_size
        value = Decimal("-Infinity")
        while left < right:
            if left & 1:
                value = max(value, self._maximum_tree[left])
                left += 1
            if right & 1:
                right -= 1
                value = max(value, self._maximum_tree[right])
            left //= 2
            right //= 2
        return value

    def _first_extreme_index(
        self,
        *,
        left: int,
        right: int,
        threshold: Decimal,
        use_maximum: bool,
    ) -> int | None:
        if left >= right:
            return None
        tree = self._maximum_tree if use_maximum else self._minimum_tree

        def cannot_match(node: int) -> bool:
            return tree[node] < threshold if use_maximum else tree[node] > threshold

        stack: list[tuple[int, int, int]] = [(1, 0, self._tree_size)]
        while stack:
            node, node_left, node_right = stack.pop()
            if node_right <= left or right <= node_left or cannot_match(node):
                continue
            if node >= self._tree_size:
                index = node - self._tree_size
                return index if index < len(self.values) else None
            middle = (node_left + node_right) // 2
            stack.append((node * 2 + 1, middle, node_right))
            stack.append((node * 2, node_left, middle))
        return None
