import numpy as np
import pandas as pd
import pytest

import turbofastapply  # noqa: F401  (registers the .turbofastapply accessor)

LARGE_N = 1000


def _large_int_series():
    return pd.Series(np.arange(LARGE_N, dtype="int64"))


# --- engine="pandas" ---------------------------------------------------


def test_engine_pandas_skips_fast_path():
    s = _large_int_series()
    expected = s.apply(lambda x: x * 2 + 1)
    result = s.turbofastapply(lambda x: x * 2 + 1, engine="pandas")
    pd.testing.assert_series_equal(result, expected)


def test_engine_pandas_never_calls_native(monkeypatch):
    s = _large_int_series()
    from turbofastapply import decide

    monkeypatch.setattr(decide, "decide", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    result = s.turbofastapply(lambda x: x * 2 + 1, engine="pandas")
    pd.testing.assert_series_equal(result, s.apply(lambda x: x * 2 + 1))


# --- engine="native" -----------------------------------------------------


def test_engine_native_succeeds_when_eligible():
    s = _large_int_series()
    expected = s.apply(lambda x: x * 2 + 1)
    result = s.turbofastapply(lambda x: x * 2 + 1, engine="native")
    pd.testing.assert_series_equal(result, expected)


def test_engine_native_raises_when_not_eligible_non_affine():
    s = _large_int_series()
    with pytest.raises(ValueError, match="not eligible"):
        s.turbofastapply(lambda x: x**2, engine="native")


def test_engine_native_succeeds_on_small_series():
    # MIN_ROWS is an engine="auto" profitability heuristic (below it, the
    # native call's fixed overhead isn't worth it), not a correctness
    # requirement — an explicit engine="native" request bypasses it and
    # still gets a correct, verified native result.
    s = pd.Series(range(10))
    expected = s.apply(lambda x: x * 2)
    result = s.turbofastapply(lambda x: x * 2, engine="native")
    pd.testing.assert_series_equal(result, expected)


def test_engine_auto_still_declines_small_series(capsys):
    # The bypass above is engine="native"-only; engine="auto" must keep
    # using MIN_ROWS to skip the fast path on small data.
    s = pd.Series(range(10))
    result = s.turbofastapply(lambda x: x * 2, verbose=True)
    pd.testing.assert_series_equal(result, s.apply(lambda x: x * 2))
    assert "needs >= 50" in capsys.readouterr().err


def test_engine_native_raises_on_dataframe_axis0():
    """Phase 5 only covers row-wise (axis=1); axis=0 (column-wise) has no
    native path regardless of the function or DataFrame size."""
    df = pd.DataFrame({"a": range(200), "b": range(200)})
    with pytest.raises(ValueError, match="not eligible"):
        df.turbofastapply(lambda col: col.sum(), engine="native")


def test_engine_native_succeeds_on_large_row_wise_dataframe():
    """The same row['a'] + row['b'] shape that used to always raise
    (before Phase 5's row-wise fast path existed) now succeeds once the
    DataFrame is large enough to be worth it."""
    df = pd.DataFrame({"a": range(200), "b": range(200)})
    expected = df.apply(lambda row: row["a"] + row["b"], axis=1)
    result = df.turbofastapply(lambda row: row["a"] + row["b"], axis=1, engine="native")
    pd.testing.assert_series_equal(result, expected)


def test_engine_native_succeeds_on_small_row_wise_dataframe():
    # Same MIN_ROWS-is-a-profitability-heuristic reasoning as the Series
    # case above, for the row-wise DataFrame path.
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    expected = df.apply(lambda row: row["a"] + row["b"], axis=1)
    result = df.turbofastapply(lambda row: row["a"] + row["b"], axis=1, engine="native")
    pd.testing.assert_series_equal(result, expected)


def test_engine_auto_still_declines_small_row_wise_dataframe(capsys):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    result = df.turbofastapply(lambda row: row["a"] + row["b"], axis=1, verbose=True)
    pd.testing.assert_series_equal(result, df.apply(lambda row: row["a"] + row["b"], axis=1))
    assert "needs >= 50" in capsys.readouterr().err


def test_engine_native_raises_with_extra_args():
    s = _large_int_series()
    with pytest.raises(ValueError, match="not eligible"):
        s.turbofastapply(lambda x, y: x + y, args=(1,), engine="native")


def test_invalid_engine_raises():
    s = pd.Series([1, 2, 3])
    with pytest.raises(ValueError, match="engine"):
        s.turbofastapply(lambda x: x, engine="bogus")


# --- verbose -------------------------------------------------------------


def test_verbose_reports_native_engine(capsys):
    s = _large_int_series()
    s.turbofastapply(lambda x: x * 2 + 1, verbose=True)
    err = capsys.readouterr().err
    assert "engine=native-int64" in err


def test_verbose_reports_pandas_fallback_reason(capsys):
    s = _large_int_series()
    s.turbofastapply(lambda x: x**2, verbose=True)
    err = capsys.readouterr().err
    assert "engine=pandas" in err
    assert "affine" in err


def test_verbose_silent_by_default(capsys):
    s = _large_int_series()
    s.turbofastapply(lambda x: x * 2 + 1)
    err = capsys.readouterr().err
    assert err == ""


# --- progress_bar ----------------------------------------------------------


def test_progress_bar_prints_for_fallback_path(capsys):
    s = pd.Series(range(200))
    result = s.turbofastapply(lambda x: x**2, progress_bar=True)
    pd.testing.assert_series_equal(result, s.apply(lambda x: x**2))
    err = capsys.readouterr().err
    assert "turbofastapply [" in err
    assert "200/200" in err


def test_progress_bar_silent_when_native_path_used(capsys):
    """The native path is one vectorized call - nothing to report progress
    on, so no progress bar should print even if requested."""
    s = _large_int_series()
    s.turbofastapply(lambda x: x * 2 + 1, progress_bar=True)
    err = capsys.readouterr().err
    assert err == ""


def test_progress_bar_on_dataframe_row_apply(capsys):
    """Uses string concatenation, not row['a'] + row['b'], so this stays
    on the pandas-fallback path — a numeric sum would now be caught by
    Phase 5's native row-affine fast path (correctly: it's a single
    vectorized call, so there's no per-row progress to report there)."""
    df = pd.DataFrame({"a": range(150), "b": range(150)})
    func = lambda row: f"{row['a']}-{row['b']}"  # noqa: E731
    result = df.turbofastapply(func, axis=1, progress_bar=True)
    pd.testing.assert_series_equal(result, df.apply(func, axis=1))
    err = capsys.readouterr().err
    assert "150/150" in err
