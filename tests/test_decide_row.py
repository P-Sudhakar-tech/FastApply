from unittest import mock

import numpy as np
import pandas as pd
import pytest

import turbofastapply  # noqa: F401  (registers the .turbofastapply accessor)
from turbofastapply import _turbofastapply, decide_row

LARGE_N = 1000


def _large_df():
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "a": rng.integers(-100, 100, size=LARGE_N),
            "b": rng.integers(-100, 100, size=LARGE_N),
            "c": rng.integers(-100, 100, size=LARGE_N),
        }
    )


# --- correctness across shapes ----------------------------------------------


@pytest.mark.parametrize(
    "func",
    [
        lambda row: row["a"] + row["b"],
        lambda row: row["a"] - row["b"],
        lambda row: row["a"] + row["b"] + row["c"],
        lambda row: 2 * row["a"] - 3 * row["b"] + row["c"] + 10,
        lambda row: row["a"],
        lambda row: -row["a"] + 5,
    ],
)
def test_row_affine_matches_pandas(func):
    df = _large_df()
    expected = df.apply(func, axis=1)
    result = df.turbofastapply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_row_affine_matches_pandas_on_float_columns():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"x": rng.normal(size=LARGE_N), "y": rng.normal(size=LARGE_N)})
    func = lambda row: 1.5 * row["x"] + 0.25 * row["y"] - 2  # noqa: E731
    expected = df.apply(func, axis=1)
    result = df.turbofastapply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_row_affine_matches_pandas_on_mixed_int_float_columns():
    df = pd.DataFrame({"a": range(LARGE_N), "b": np.linspace(0, 1, LARGE_N)})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    expected = df.apply(func, axis=1)
    result = df.turbofastapply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_row_affine_int_dtype_preserved_when_result_is_whole():
    df = pd.DataFrame({"a": range(LARGE_N), "b": range(LARGE_N)})
    result = df.turbofastapply(lambda row: row["a"] + row["b"], axis=1)
    assert result.dtype == np.int64


# --- dispatch correctness (engaged vs. declined) ----------------------------


def test_row_affine_actually_calls_native(monkeypatch):
    df = _large_df()
    with mock.patch.object(_turbofastapply, "row_affine_f64", wraps=_turbofastapply.row_affine_f64) as spy:
        result = df.turbofastapply(lambda row: row["a"] + row["b"], axis=1)
    assert result.equals(df.apply(lambda row: row["a"] + row["b"], axis=1))
    spy.assert_called_once()


@pytest.mark.parametrize(
    "func",
    [
        lambda row: row["a"] * row["b"],  # product of two columns: not affine
        lambda row: row["a"] if row["a"] > 0 else row["b"],  # branches on data
        lambda row: row["a"] ** 2,
        lambda row: str(row["a"]),  # non-numeric output
    ],
)
def test_non_affine_row_func_declines_and_falls_back_correctly(func):
    df = _large_df()
    assert decide_row.decide(df, func).result is None
    expected = df.apply(func, axis=1)
    result = df.turbofastapply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_small_dataframe_never_engages():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    assert decide_row.decide(df, lambda row: row["a"] + row["b"]).result is None


def test_wide_dataframe_over_column_cap_declines():
    n_cols = decide_row.MAX_COLUMNS + 5
    df = pd.DataFrame({f"c{i}": range(LARGE_N) for i in range(n_cols)})
    func = lambda row: sum(row[c] for c in df.columns)  # noqa: E731
    decision = decide_row.decide(df, func)
    assert decision.result is None
    assert "columns" in decision.reason


def test_referenced_non_numeric_column_declines():
    df = pd.DataFrame({"a": range(LARGE_N), "b": [f"item_{i}" for i in range(LARGE_N)]})
    decision = decide_row.decide(df, lambda row: row["a"] + len(row["b"]))
    assert decision.result is None


def test_unreferenced_non_numeric_column_does_not_block_acceleration():
    """A column the function never touches (e.g. an id/name column
    alongside numeric ones) shouldn't disable the fast path just because
    it isn't numeric — only columns the output actually depends on need
    to be. This is the exact shape that showed up as a near-1.0x
    "speedup" in examples/benchmark.py before this was fixed: the
    DataFrame there has a string `name` column the row func never
    touches, and the old dtype check required *every* column to be
    numeric regardless of relevance."""
    df = pd.DataFrame(
        {
            "a": range(LARGE_N),
            "b": range(LARGE_N),
            "name": [f"item_{i}" for i in range(LARGE_N)],
        }
    )
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    decision = decide_row.decide(df, func)
    assert decision.result is not None
    assert decision.engine == "native-row-affine"
    pd.testing.assert_series_equal(decision.result, df.apply(func, axis=1))


def test_axis0_never_uses_row_fast_path():
    """Phase 5 is row-wise only; axis=0 (column-wise) always falls back,
    even for a function that would be a trivial column-wise analogue."""
    df = pd.DataFrame({"a": range(LARGE_N), "b": range(LARGE_N)})
    expected = df.apply(lambda col: col.sum())
    result = df.turbofastapply(lambda col: col.sum())  # axis=0 default
    pd.testing.assert_series_equal(result, expected)


# --- verbose reporting -------------------------------------------------------


def test_verbose_reports_native_row_engine(capsys):
    df = _large_df()
    df.turbofastapply(lambda row: row["a"] + row["b"], axis=1, verbose=True)
    err = capsys.readouterr().err
    assert "engine=native-row-affine" in err


# --- edge cases (Phase 7 hardening) -----------------------------------------


def test_nan_in_used_column_outside_sample_does_not_silently_corrupt_result():
    """Same class of bug as decide.py's equivalent test: a NaN in a
    column the function depends on, outside the ~12 sampled rows, would
    previously pass verification undetected and then get the naive
    linear-combination treatment even when the real function has
    explicit NaN-handling logic."""
    a = [float(x) for x in range(LARGE_N)]
    a[40] = float("nan")  # off the sampling stride
    df = pd.DataFrame({"a": a, "b": list(range(LARGE_N))})

    def func(row):
        return -999.0 if np.isnan(row["a"]) else row["a"] + row["b"]

    assert decide_row.decide(df, func).result is None
    pd.testing.assert_series_equal(df.turbofastapply(func, axis=1), df.apply(func, axis=1))


def test_nan_in_unused_column_does_not_block_acceleration():
    """A NaN in a column the function never references shouldn't disable
    the fast path — only used columns' NaN-safety matters."""
    df = pd.DataFrame(
        {
            "a": range(LARGE_N),
            "b": range(LARGE_N),
            "unused": [float("nan")] * LARGE_N,
        }
    )
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    decision = decide_row.decide(df, func)
    assert decision.result is not None
    pd.testing.assert_series_equal(decision.result, df.apply(func, axis=1))


def test_single_row_dataframe_falls_back():
    df = pd.DataFrame({"a": [1], "b": [2]})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    assert decide_row.decide(df, func).result is None
    pd.testing.assert_series_equal(df.turbofastapply(func, axis=1), df.apply(func, axis=1))


def test_unused_float_column_upcasts_result_to_float_matching_pandas():
    """pandas' df.apply(axis=1) builds one Series per row spanning ALL
    columns before func ever runs, so an unused FLOAT column (unlike an
    unused string column, see the "does not block acceleration" test
    above) upcasts that row to float64 and therefore the result too —
    even though the function only touches the int columns. The fast
    path must reproduce this exactly, not just get the values right."""
    df = pd.DataFrame(
        {
            "a": range(LARGE_N),
            "b": range(LARGE_N),
            "unused_float": [1.5] * LARGE_N,
        }
    )
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    expected = df.apply(func, axis=1)
    assert expected.dtype == np.float64  # confirms the pandas quirk this test is about
    decision = decide_row.decide(df, func)
    assert decision.result is not None
    pd.testing.assert_series_equal(decision.result, expected)


def test_empty_dataframe_falls_back():
    df = pd.DataFrame({"a": pd.Series(dtype="int64"), "b": pd.Series(dtype="int64")})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    assert decide_row.decide(df, func).result is None
    result = df.turbofastapply(func, axis=1)
    expected = df.apply(func, axis=1)
    assert len(result) == len(expected) == 0
