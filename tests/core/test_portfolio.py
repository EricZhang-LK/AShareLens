from datetime import date

import pytest

from asharelens.core.models import SelectionCandidate
from asharelens.core.portfolio import build_equal_weight_targets


def test_equal_weight_targets_respect_top_n() -> None:
    candidates = [
        SelectionCandidate(
            symbol=f"demo.{index}",
            signal_date=date(2026, 1, 5),
            selected=True,
            score=1 - index / 10,
            rank=index + 1,
        )
        for index in range(3)
    ]

    targets = build_equal_weight_targets(candidates, top_n=2, max_weight=0.6)

    assert targets == {"demo.0": 0.5, "demo.1": 0.5}


def test_equal_weight_targets_ignore_excluded_candidates() -> None:
    candidates = [
        SelectionCandidate(
            symbol="demo.selected",
            signal_date=date(2026, 1, 5),
            selected=True,
            score=0.7,
            rank=2,
        ),
        SelectionCandidate(
            symbol="demo.excluded",
            signal_date=date(2026, 1, 5),
            selected=False,
            score=0.9,
            rank=1,
        ),
    ]

    targets = build_equal_weight_targets(candidates, top_n=2, max_weight=0.6)

    assert targets == {"demo.selected": 0.6}


def test_equal_weight_targets_reject_impossible_full_investment_limit() -> None:
    with pytest.raises(ValueError, match="top_n multiplied by max_weight"):
        build_equal_weight_targets([], top_n=2, max_weight=0.4)


@pytest.mark.parametrize(
    ("top_n", "max_weight"),
    [(0, 1.0), (2, 0.0), (2, 1.1)],
)
def test_equal_weight_targets_reject_invalid_configuration(
    top_n: int,
    max_weight: float,
) -> None:
    with pytest.raises(ValueError):
        build_equal_weight_targets([], top_n=top_n, max_weight=max_weight)
