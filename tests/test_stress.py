"""Phase 7 hardening: correctness at scale, specifically past
PARALLEL_THRESHOLD=50_000 (src/lib.rs) where the Rust side switches from
a sequential loop to rayon parallel iterators. Every other test in this
repo stays under that threshold, so it's never been exercised — this
file is about correctness at that scale, not speed (examples/benchmark.py
covers speed)."""

import numpy as np
import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)
from turboply import decide_row

PAST_PARALLEL_THRESHOLD = 60_000  # src/lib.rs PARALLEL_THRESHOLD is 50_000


@pytest.mark.parametrize(
    "func",
    [
        lambda x: x * 2 + 1,
        lambda x: x - 100,
        lambda x: -x,
        abs,
    ],
)
def test_numeric_fast_path_correct_past_parallel_threshold_int(func):
    s = pd.Series(np.arange(-PAST_PARALLEL_THRESHOLD // 2, PAST_PARALLEL_THRESHOLD // 2, dtype="int64"))
    expected = s.apply(func)
    result = s.turboply(func)
    pd.testing.assert_series_equal(result, expected)


def test_numeric_fast_path_correct_past_parallel_threshold_float():
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(size=PAST_PARALLEL_THRESHOLD))
    func = lambda x: x * 1.5 - 0.25  # noqa: E731
    expected = s.apply(func)
    result = s.turboply(func)
    pd.testing.assert_series_equal(result, expected)


def test_row_affine_correct_past_parallel_threshold():
    rng = np.random.default_rng(1)
    df = pd.DataFrame(
        {
            "a": rng.integers(-1000, 1000, size=PAST_PARALLEL_THRESHOLD),
            "b": rng.integers(-1000, 1000, size=PAST_PARALLEL_THRESHOLD),
            "c": rng.integers(-1000, 1000, size=PAST_PARALLEL_THRESHOLD),
        }
    )
    func = lambda row: 2 * row["a"] - row["b"] + 3 * row["c"] + 7  # noqa: E731
    decision = decide_row.decide(df, func)
    assert decision.result is not None  # confirm this actually exercised the native path
    expected = df.apply(func, axis=1)
    pd.testing.assert_series_equal(decision.result, expected)


def test_str_upper_correct_past_parallel_threshold():
    """Correctness only — the string path isn't faster at any scale (see
    claude.md), but it must still be right at every scale."""
    s = pd.Series([f"item_{i}_mixed_CASE" for i in range(PAST_PARALLEL_THRESHOLD)])
    result = s.turboply(str.upper, engine="native")
    expected = s.apply(str.upper)
    pd.testing.assert_series_equal(result, expected)


def test_str_contains_correct_past_parallel_threshold():
    s = pd.Series([f"item_{i}_mixed" for i in range(PAST_PARALLEL_THRESHOLD)])
    result = s.turboply.str.contains(r"item_\d*5_")
    expected = s.str.contains(r"item_\d*5_", regex=True)
    pd.testing.assert_series_equal(result, expected)
