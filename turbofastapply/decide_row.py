"""Dispatch heuristic for the DataFrame row-wise (axis=1) fast path
(Phase 5).

Row-wise functions take a whole row (a pandas Series indexed by column
name) rather than a single scalar, so the univariate affine trick from
decide.py — probe at x=0 and x=1, two points fully determine a line —
generalizes to the multivariate case: probe at the all-zero row (gives
the intercept) and at each unit-basis row (exactly one column set to 1,
the rest 0 — each gives intercept + that column's coefficient). N+1
points fully determine an N-variable affine function the same way two
points fully determine a one-variable one. `row['a'] + row['b']` is
exactly this shape with coefficients (1, 1) and intercept 0.

Probing substitutes float placeholder values for every column regardless
of its real dtype, so it works even when the DataFrame has non-numeric
columns the function never touches (an id/name column alongside numeric
ones, say) — after probing, only columns with a nonzero coefficient
(i.e. ones the function's output actually depends on) need to be numeric
in reality; unreferenced columns' dtypes are irrelevant and never
checked. Probing cost is still O(total columns) though, so this caps out
at MAX_COLUMNS regardless of how many end up used — wide DataFrames get
the Phase 3 threaded-parallel fallback instead.

Same safety net as everywhere else: the guessed coefficients are always
verified against real rows from the actual DataFrame before being
trusted on the full data.
"""

import math

import numpy as np
import pandas as pd

from . import _turbofastapply
from .decide import Decision, _is_real_number

MIN_ROWS = 50
SAMPLE_SIZE = 12
MAX_COLUMNS = 20
_TOL = 1e-9


def _probe_row(index, values):
    # `index` is a pre-built pd.Index, reused across every probe call
    # (see decide() below) rather than a plain column list rebuilt into
    # a fresh Index by pd.Series() on every call. Profiling found
    # Index construction (ensure_index/Index.__new__) was a real,
    # measurable share of decide_row()'s total cost at small row
    # counts, where it's a fixed cost paid by every call regardless of
    # DataFrame size -- probing already uses synthetic placeholder
    # values disconnected from the real data's dtypes (see the module
    # docstring), so reusing one Index object here carries no
    # correctness risk the way touching the verification sample's
    # per-row construction below would.
    return pd.Series(values, index=index)


def _sample_positions(n):
    step = max(1, n // SAMPLE_SIZE)
    return list(range(0, n, step))[:SAMPLE_SIZE]


def _pandas_row_would_be_int(df, used_columns):
    """Mirror pandas' own df.apply(axis=1) row-construction dtype rule,
    which depends on ALL columns, not just the ones the function uses:
    each row is materialized as one pandas Series spanning every column
    before func ever sees it. If every column is numeric, that row
    Series is a single homogeneous numeric array — upcast to float64 if
    ANY column (used or not) is float, even one the function never
    touches. If any column is non-numeric (e.g. a string id column),
    the row instead becomes dtype=object, and each column's original
    scalar type (including int) survives untouched regardless of what
    other columns hold. Confirmed empirically (not assumed) with cases
    covering unused float columns, unused string columns, and both
    together — see tests/test_decide_row.py."""
    dtypes = df.dtypes
    if all(pd.api.types.is_numeric_dtype(dt) for dt in dtypes):
        return all(pd.api.types.is_integer_dtype(dt) for dt in dtypes)
    return all(pd.api.types.is_integer_dtype(df[col].dtype) for col in used_columns)


def decide(df, func, *, enforce_min_rows=True):
    """Return a Decision for df.apply(func, axis=1).

    `enforce_min_rows=False` (used by the accessor only when the caller
    explicitly requested `engine="native"`) skips the MIN_ROWS decline —
    same rationale as decide.py's equivalent parameter: it's a pure
    engine="auto" profitability heuristic, not a correctness requirement.
    Column probing doesn't depend on row count at all (it evaluates func
    on synthetic probe rows, never real data rows), and the sample
    verification below degrades cleanly to a no-op for zero real rows
    rather than misbehaving."""
    if enforce_min_rows and len(df) < MIN_ROWS:
        return Decision(None, "pandas", f"dataframe has {len(df)} rows, needs >= {MIN_ROWS}")
    if df.shape[1] == 0:
        return Decision(None, "pandas", "no columns")
    if df.shape[1] > MAX_COLUMNS:
        return Decision(None, "pandas", f"{df.shape[1]} columns exceeds probing cap of {MAX_COLUMNS}")

    columns = list(df.columns)
    n_cols = len(columns)
    col_index = pd.Index(columns)  # built once, reused for every probe row below

    try:
        baseline = func(_probe_row(col_index, [0.0] * n_cols))
    except Exception as exc:
        return Decision(None, "pandas", f"function raised on probe row: {exc!r}")
    if not _is_real_number(baseline):
        return Decision(None, "pandas", "function output at probe row isn't a real number")

    coeffs = []
    # One mutable list, reused across every unit-basis probe (set the
    # active column to 1.0, probe, reset to 0.0) instead of allocating a
    # fresh n_cols-length list per column. Safe to reuse: pd.Series()
    # converts the list to its own array immediately on construction, so
    # each _probe_row() call's result is independent of later mutations
    # here.
    values = [0.0] * n_cols
    for i in range(n_cols):
        values[i] = 1.0
        try:
            value = func(_probe_row(col_index, values))
        except Exception as exc:
            return Decision(None, "pandas", f"function raised on probe row: {exc!r}")
        finally:
            values[i] = 0.0
        if not _is_real_number(value):
            return Decision(None, "pandas", "function output at probe row isn't a real number")
        coeffs.append(value - baseline)

    used = [(col, c) for col, c in zip(columns, coeffs) if abs(c) > _TOL]
    used_columns = [col for col, _ in used]

    if not all(pd.api.types.is_numeric_dtype(df[col].dtype) for col in used_columns):
        return Decision(None, "pandas", "a column the function's output actually depends on isn't numeric")

    # Built once here and reused for the NaN check, the sample
    # verification's used_values, AND the final native call below --
    # profiling found df[col].to_numpy() and df[col].isna() were each
    # being paid for twice (once per purpose) at small row counts, where
    # that redundant second full-column pass is a fixed cost independent
    # of how much data there actually is to process.
    arrays = [df[col].to_numpy(dtype=float) for col in used_columns]

    # Same reasoning as decide.py's equivalent check: a NaN in a used
    # column, outside the sampled rows below, would silently get the
    # naive linear-combination treatment even if func has explicit
    # NaN-handling logic that differs — checked across the whole column,
    # not just the sample, for the same reason. np.isnan() on the raw
    # array is used instead of df[col].isna() -- measurably cheaper than
    # pandas' own Series.isna(), and arrays is already in hand above.
    if any(np.isnan(a).any() for a in arrays):
        return Decision(None, "pandas", "a used column contains NaN — can't safely trust a sample-only guess")

    positions = _sample_positions(len(df))
    sample = df.iloc[positions]
    # Precomputed once, outside the loop: used_values[i] holds the used
    # columns' values for sample row i, positionally. func(row) below
    # still gets the exact same real, .iterrows()-produced row Series
    # either way -- this only changes how *this* code re-reads values
    # from that row afterward for its own predicted-vs-actual check,
    # replacing a label lookup (row[col]: index engine hash/search, paid
    # once per used column per sample row) with a positional numpy read.
    # Sliced straight out of `arrays` above (fancy indexing) rather than
    # sample[used_columns].to_numpy(), which pays for DataFrame column
    # selection machinery on top of the array copy -- profiling found
    # that combination was, by a wide margin, the single largest cost
    # in this function at small row counts.
    used_values = np.column_stack([a[positions] for a in arrays]) if used_columns else None
    for sample_pos, (_, row) in enumerate(sample.iterrows()):
        try:
            actual = func(row)
        except Exception:
            return Decision(None, "pandas", "function raised on a real sample row")
        if not _is_real_number(actual):
            return Decision(None, "pandas", "function output on a real row isn't a real number")
        actual = float(actual)
        if used_columns:
            predicted = baseline + sum(c * v for (_, c), v in zip(used, used_values[sample_pos]))
        else:
            predicted = baseline
        if math.isnan(predicted) or math.isnan(actual):
            return Decision(None, "pandas", "NaN encountered during verification")
        tol = _TOL * max(1.0, abs(actual))
        if abs(predicted - actual) > tol:
            return Decision(
                None, "pandas", "function isn't a linear combination of columns on a sample of real rows"
            )

    if used_columns:
        # `arrays` was already built above for the NaN check and sample
        # verification -- reused here rather than recomputed.
        used_coeffs = [c for _, c in used]
        try:
            out = _turbofastapply.row_affine_f64(arrays, used_coeffs, baseline)
        except Exception as exc:
            return Decision(None, "pandas", f"native call raised on full dataframe: {exc!r}")
    else:
        # func's output doesn't depend on any column (a constant) — still
        # correct to accelerate, just skip the native call entirely.
        out = np.full(len(df), baseline, dtype=float)

    result = pd.Series(out, index=df.index)
    if used_columns and np.all(np.isclose(out, np.round(out))) and _pandas_row_would_be_int(df, used_columns):
        result = result.round().astype("int64")

    coeff_str = ", ".join(f"{c:g}*{col}" for col, c in used) or "constant"
    return Decision(result, "native-row-affine", f"row is {coeff_str} + {baseline:g}, verified on a real sample")
