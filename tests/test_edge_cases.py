"""Phase 7 hardening: edge cases across every dispatch tier — empty and
1-row inputs, categorical dtype, object dtype, integer overflow, and
mixed NaN/inf — verified against plain pandas rather than assumed safe.
"""

import numpy as np
import pandas as pd
import pytest

import turbofastapply  # noqa: F401  (registers the .turbofastapply accessor)
from turbofastapply import decide, decide_row, decide_str, parallel

LARGE_N = 1000


# --- empty inputs ------------------------------------------------------------


def test_empty_series_numeric():
    s = pd.Series([], dtype="int64")
    func = lambda x: x * 2 + 1  # noqa: E731
    assert decide.try_numeric_fast_path(s, func) is None
    pd.testing.assert_series_equal(s.turbofastapply(func), s.apply(func))


def test_empty_series_string():
    s = pd.Series([], dtype=object)
    assert decide_str.decide(s, str.upper).result is None
    pd.testing.assert_series_equal(s.turbofastapply(str.upper), s.apply(str.upper))


def test_empty_dataframe_row_wise():
    df = pd.DataFrame({"a": pd.Series(dtype="int64"), "b": pd.Series(dtype="int64")})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    result = df.turbofastapply(func, axis=1)
    expected = df.apply(func, axis=1)
    assert len(result) == len(expected) == 0


def test_empty_series_parallel_fallback():
    s = pd.Series([], dtype="int64")
    assert parallel.try_parallel_fallback(s, lambda x: x) is None


# --- 1-row / tiny inputs -----------------------------------------------------


def test_one_row_series():
    s = pd.Series([42])
    func = lambda x: x * 3 + 7  # noqa: E731
    pd.testing.assert_series_equal(s.turbofastapply(func), s.apply(func))


def test_one_row_dataframe_row_wise():
    df = pd.DataFrame({"a": [1], "b": [2]})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    pd.testing.assert_series_equal(df.turbofastapply(func, axis=1), df.apply(func, axis=1))


# --- categorical dtype --------------------------------------------------------


def test_categorical_series_falls_back_correctly():
    s = pd.Series(list(range(LARGE_N)) * 2, dtype="category")
    func = lambda x: x * 2 + 1  # noqa: E731
    assert decide.try_numeric_fast_path(s, func) is None
    pd.testing.assert_series_equal(s.turbofastapply(func), s.apply(func))


def test_categorical_column_in_row_wise_falls_back_correctly():
    df = pd.DataFrame(
        {
            "a": range(LARGE_N),
            "cat": pd.Series(["x", "y"] * (LARGE_N // 2), dtype="category"),
        }
    )
    func = lambda row: row["a"] * 2  # noqa: E731
    # "cat" is unused, but it's non-numeric, so it still must not corrupt
    # the result — this exercises decide_row's used-vs-unused logic
    # against a dtype kind (category) distinct from plain object/string.
    result = df.turbofastapply(func, axis=1)
    expected = df.apply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


# --- object dtype holding numeric-like Python objects ------------------------


def test_object_dtype_numeric_series_falls_back():
    """An object-dtype Series holding Python ints (not a proper numeric
    dtype) shouldn't be mistaken for one."""
    s = pd.Series([i for i in range(LARGE_N)], dtype=object)
    func = lambda x: x * 2 + 1  # noqa: E731
    assert decide.try_numeric_fast_path(s, func) is None
    pd.testing.assert_series_equal(s.turbofastapply(func), s.apply(func))


# --- integer overflow ---------------------------------------------------------


def test_large_int_values_near_int64_range_stay_correct():
    """affine_i64 uses wrapping arithmetic (see src/lib.rs) rather than
    panicking on overflow, matching NumPy's own silent-wraparound
    behavior for int64 rather than Python's arbitrary-precision ints —
    so this checks the native path agrees with pandas specifically in
    the regime where wraparound could plausibly differ (large but not
    overflowing values), not that overflow itself is "handled" in some
    exact sense neither library defines consistently."""
    big = 2**40
    s = pd.Series(np.arange(big, big + LARGE_N, dtype=np.int64))
    func = lambda x: x * 2 + 1  # noqa: E731
    result = s.turbofastapply(func)
    expected = s.apply(func)
    pd.testing.assert_series_equal(result, expected)


# --- mixed NaN/inf across dtypes and tiers -----------------------------------


def test_series_all_nan_falls_back():
    s = pd.Series([float("nan")] * LARGE_N)
    func = lambda x: x * 2 + 1  # noqa: E731
    assert decide.try_numeric_fast_path(s, func) is None
    result = s.turbofastapply(func)
    expected = s.apply(func)
    pd.testing.assert_series_equal(result, expected)


def test_dataframe_all_columns_nan_row_wise_falls_back():
    df = pd.DataFrame({"a": [float("nan")] * LARGE_N, "b": [float("nan")] * LARGE_N})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    assert decide_row.decide(df, func).result is None
    result = df.turbofastapply(func, axis=1)
    expected = df.apply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_string_series_with_only_nulls_falls_back():
    s = pd.Series([None] * LARGE_N, dtype=object)
    assert decide_str.decide(s, str.upper).result is None


# --- boolean dtype -------------------------------------------------------------


def test_boolean_series_declines_and_falls_back_correctly():
    """bool is numeric-ish in pandas but its apply() dtype inference is
    genuinely ambiguous for black-box affine probing: pandas keeps bool
    dtype only for func = literal identity, but promotes to int64 for
    anything arithmetically equivalent (even `x*1+0`) — indistinguishable
    from our probing's perspective, since both give coefficients (1, 0).
    decide.py declines bool outright rather than guessing; this checks
    that declining still produces a correct (if unaccelerated) result
    for both the identity case (pandas keeps bool) and an arithmetic
    case (pandas promotes to int64), via the ordinary fallback path."""
    s = pd.Series([True, False] * (LARGE_N // 2))
    assert decide.try_numeric_fast_path(s, lambda x: x) is None

    identity = lambda x: x  # noqa: E731
    pd.testing.assert_series_equal(s.turbofastapply(identity), s.apply(identity))

    arithmetic = lambda x: x * 2 + 1  # noqa: E731
    pd.testing.assert_series_equal(s.turbofastapply(arithmetic), s.apply(arithmetic))
