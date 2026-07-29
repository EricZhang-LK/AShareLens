"""Portfolio construction rules independent of persistence and execution."""

from __future__ import annotations

from collections.abc import Iterable

from asharelens.core.models import SelectionCandidate


def build_equal_weight_targets(
    candidates: Iterable[SelectionCandidate],
    *,
    top_n: int,
    max_weight: float,
) -> dict[str, float]:
    """Build deterministic Top-N equal weights while allowing residual cash."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if not 0 < max_weight <= 1:
        raise ValueError("max_weight must be in (0, 1]")
    if top_n * max_weight < 1:
        raise ValueError("top_n multiplied by max_weight must allow full investment")

    selected = sorted(
        (candidate for candidate in candidates if candidate.selected),
        key=lambda candidate: (
            candidate.rank if candidate.rank is not None else float("inf"),
            candidate.symbol,
        ),
    )
    chosen = selected[:top_n]
    if not chosen:
        return {}

    weight = min(1 / len(chosen), max_weight)
    return {candidate.symbol: weight for candidate in chosen}
