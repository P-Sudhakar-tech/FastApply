import pandas as pd
import pytest

import turbofastapply  # noqa: F401  (registers the .turbofastapply accessors)


def test_series_accessor_exists():
    s = pd.Series([1, 2, 3])
    assert hasattr(s, "turbofastapply")


def test_dataframe_accessor_exists():
    df = pd.DataFrame({"a": [1, 2, 3]})
    assert hasattr(df, "turbofastapply")


@pytest.mark.parametrize(
    "func",
    [
        lambda x: x * 2,
        lambda x: x**2,
        str,
        lambda x: x if x % 2 == 0 else -x,
    ],
)
def test_series_apply_matches_pandas(func):
    s = pd.Series(range(-5, 6))
    expected = s.apply(func)
    result = s.turbofastapply.apply(func)
    pd.testing.assert_series_equal(result, expected)


def test_series_apply_with_args_kwargs_matches_pandas():
    s = pd.Series([1, 2, 3])

    def add(x, y, z=0):
        return x + y + z

    expected = s.apply(add, args=(10,), z=1)
    result = s.turbofastapply.apply(add, args=(10,), z=1)
    pd.testing.assert_series_equal(result, expected)


def test_dataframe_apply_matches_pandas():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    expected = df.apply(lambda col: col.sum())
    result = df.turbofastapply.apply(lambda col: col.sum())
    pd.testing.assert_series_equal(result, expected)


def test_dataframe_apply_axis1_matches_pandas():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    expected = df.apply(lambda row: row["a"] + row["b"], axis=1)
    result = df.turbofastapply.apply(lambda row: row["a"] + row["b"], axis=1)
    pd.testing.assert_series_equal(result, expected)


def test_empty_series_fallback():
    s = pd.Series([], dtype=float)
    expected = s.apply(lambda x: x)
    result = s.turbofastapply.apply(lambda x: x)
    pd.testing.assert_series_equal(result, expected)


def test_series_direct_call_matches_apply():
    """s.turbofastapply(func) is the primary API; .apply() is kept as an alias."""
    s = pd.Series(range(-5, 6))
    func = lambda x: x * 3 + 1  # noqa: E731
    pd.testing.assert_series_equal(s.turbofastapply(func), s.turbofastapply.apply(func))
    pd.testing.assert_series_equal(s.turbofastapply(func), s.apply(func))


def test_dataframe_direct_call_matches_apply():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    func = lambda row: row["a"] + row["b"]  # noqa: E731
    pd.testing.assert_series_equal(
        df.turbofastapply(func, axis=1), df.turbofastapply.apply(func, axis=1)
    )


def test_turbofastapply_accessor_is_callable():
    s = pd.Series([1, 2, 3])
    assert callable(s.turbofastapply)
