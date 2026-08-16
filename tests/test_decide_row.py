from unittest import mock

import numpy as np
import pandas as pd
import pytest

import turboply  # noqa: F401  (registers the .turboply accessor)
from turboply import _turboply, decide_row

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
    result = df.turboply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_row_affine_matches_pandas_on_float_columns():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"x": rng.normal(size=LARGE_N), "y": rng.normal(size=LARGE_N)})
    func = lambda row: 1.5 * row["x"] + 0.25 * row["y"] - 2  # noqa: E731
    expected = df.apply(func, axis=1)
    result = df.turboply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_row_affine_matches_pandas_on_mixed_int_float_columns():
    df = pd.DataFrame({"a": range(LARGE_N), "b": np.linspace(0, 1, LARGE_N)})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    expected = df.apply(func, axis=1)
    result = df.turboply(func, axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_row_affine_int_dtype_preserved_when_result_is_whole():
    df = pd.DataFrame({"a": range(LARGE_N), "b": range(LARGE_N)})
    result = df.turboply(lambda row: row["a"] + row["b"], axis=1)
    assert result.dtype == np.int64


# --- dispatch correctness (engaged vs. declined) ----------------------------


def test_row_affine_actually_calls_native(monkeypatch):
    df = _large_df()
    with mock.patch.object(_turboply, "row_affine_f64", wraps=_turboply.row_affine_f64) as spy:
        result = df.turboply(lambda row: row["a"] + row["b"], axis=1)
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
    result = df.turboply(func, axis=1)
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
    result = df.turboply(lambda col: col.sum())  # axis=0 default
    pd.testing.assert_series_equal(result, expected)


# --- verbose reporting -------------------------------------------------------


def test_verbose_reports_native_row_engine(capsys):
    df = _large_df()
    df.turboply(lambda row: row["a"] + row["b"], axis=1, verbose=True)
    err = capsys.readouterr().err
    assert "engine=native-row-affine" in err
