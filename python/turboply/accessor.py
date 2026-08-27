"""pandas accessor: numeric fast path (Phase 2), whitelisted string fast
path (Phase 4), DataFrame row-wise fast path (Phase 5), sampling-based
parallel fallback for arbitrary callables (Phase 3), and a
pandas-equivalent fallback for everything else — plus Phase 6 UX polish:
engine selection, verbose routing explanations, and an optional progress
bar for whichever path ends up doing a row-by-row Python loop.

The accessor is directly callable — `s.turboply(func)` — instead of
requiring the `.apply()` method name. `.apply()` is kept as an alias for
readers coming from `pandas.apply()`, but the direct-call form is the
primary, documented API. `s.turboply.str.contains(pattern)` /
`.replace(pattern, repl)` mirror pandas' own `.str` accessor for the two
regex ops that need arguments a lambda-probing approach can't safely
recover (see str_accessor.py).

Series tries, in order, under `engine="auto"`:
  1. Native numeric fast path (decide.py) — vectorized, single call.
  2. Threaded parallel fallback (parallel.py) — only engages when a
     sample measurement shows it's actually faster than serial (true for
     I/O-bound or otherwise GIL-releasing callables; a no-op for
     CPU-bound pure Python, which the GIL prevents from parallelizing).
  3. Plain pandas .apply().

The native string fast path (decide_str.py — exact identity match against
str.upper/.lower/.strip, verified on a sample) is deliberately NOT in the
"auto" chain: benchmarked from 500 to 1,000,000 rows, it's consistently
~0.6-0.8x plain pandas, never faster (owned-String FFI round-trip costs
more than CPython's already-fast built-in string methods save — unlike
the numeric path's genuine zero-copy numpy view). It's only reachable via
`engine="native"` (an explicit override, correctness-verified as always
but without an implied speed promise) or `.turboply.str.contains()`/
`.replace()` (str_accessor.py), which the same caveat applies to.

DataFrame row-wise (axis=1) tries the same shape, with tier 1 being
decide_row.py's row-affine detection instead — axis=0 (column-wise) has
no native fast path (Phase 5 only covers row-wise), so it only ever gets
tiers 3-4.

`engine`:
  - "auto" (default) — try the native/string/row tiers then the parallel
    tier, silently fall back to plain pandas if none is eligible.
  - "native" — require a native tier; raises ValueError with the specific
    reason if the callable isn't eligible.
  - "pandas" — skip every accelerated tier and always use plain pandas
    .apply().

`verbose=True` prints which tier was chosen and why to stderr.
`progress_bar=True` reports progress for the pandas fallback path only —
none of the other tiers do a single-threaded row-by-row loop, so there's
no equivalent per-row progress to report for them.

`.turboply` on the result of `.groupby(...)` (DataFrameGroupBy or
SeriesGroupBy — see TurboplyGroupByAccessor below) is a correctness-only
passthrough to `GroupBy.apply()`: no native fast path exists for it yet,
so `engine="auto"`/`"pandas"` both always use plain pandas and
`engine="native"` raises. pandas has no `register_*_groupby_accessor`
the way it does for Series/DataFrame/Index, so this attaches the
accessor descriptor directly to the GroupBy classes instead.
"""

import sys

import pandas as pd

from . import decide, decide_row, decide_str, parallel
from .progress import with_progress
from .str_accessor import TurboplyStrAccessor

try:
    # The long-lived internal path; pandas.api.typing (a public alias for
    # the same classes) only exists on newer pandas, so this is what
    # actually covers pyproject.toml's pandas>=1.5 floor.
    from pandas.core.groupby.generic import DataFrameGroupBy, SeriesGroupBy
except ImportError:  # pragma: no cover - hedge against a future pandas reorg
    from pandas.api.typing import DataFrameGroupBy, SeriesGroupBy

_ENGINES = ("auto", "native", "pandas")


def _check_engine(engine):
    if engine not in _ENGINES:
        raise ValueError(f"engine must be one of {_ENGINES}, got {engine!r}")


def _log(verbose, label, engine, reason):
    if verbose:
        print(f"[turboply] {label}: engine={engine} - {reason}", file=sys.stderr)


def _decide_series(series, func, engine):
    """Try the numeric fast path, then — only under engine="native" — the
    string fast path. Prefers reporting whichever decision is more
    relevant to the Series' actual dtype when both decline, so
    verbose/error messages point at the real reason rather than an
    irrelevant one from the other tier.

    decide_str's native path is NOT tried under engine="auto": extensive
    benchmarking (500 to 1,000,000 rows, all four whitelisted ops) found
    it's consistently ~0.6-0.8x plain pandas, never faster, because the
    owned-String round-trip through the Rust boundary (allocate + copy on
    the way in, allocate + copy new Python str objects on the way out,
    plus constructing the result Series) costs more than CPython's
    already-fast built-in string methods save — unlike the numeric path,
    which gets a genuine zero-copy view into the numpy buffer. "auto"
    promises "never worse than plain pandas, sometimes better", so it
    skips a tier proven to only ever be worse. engine="native" is an
    explicit override — the caller is asking for the compiled path
    regardless — so it still tries decide_str, correctness-verified as
    always, just without an implied performance promise. See claude.md."""
    decision = decide.decide(series, func, enforce_min_rows=(engine != "native"))
    if decision.result is not None:
        return decision
    if engine != "native":
        return decision

    str_decision = decide_str.decide(series, func)
    if str_decision.result is not None:
        return str_decision
    if not pd.api.types.is_numeric_dtype(series.dtype):
        return str_decision
    return decision


def _parallel_decision_log(verbose, label, result):
    if result is not None:
        _log(
            verbose,
            label,
            "threaded-parallel",
            f"sample of {parallel.SAMPLE_ROWS} rows measured >= {parallel.MIN_SPEEDUP}x faster threaded than serial",
        )


@pd.api.extensions.register_series_accessor("turboply")
class TurboplySeriesAccessor:
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    @property
    def str(self):
        return TurboplyStrAccessor(self._obj)

    def __call__(self, func, *args, engine="auto", verbose=False, progress_bar=False, **kwargs):
        _check_engine(engine)
        series = self._obj
        no_extra_args = not args and not kwargs

        if engine != "pandas" and no_extra_args:
            decision = _decide_series(series, func, engine)
            _log(verbose, "series", decision.engine, decision.reason)
            if decision.result is not None:
                return decision.result
            if engine == "native":
                raise ValueError(f"engine='native' requested but not eligible: {decision.reason}")

            parallel_result = parallel.try_parallel_fallback(series, func)
            _parallel_decision_log(verbose, "series", parallel_result)
            if parallel_result is not None:
                return parallel_result
        else:
            reason = (
                "engine='pandas' forced"
                if engine == "pandas"
                else "extra args/kwargs passed, fast path only supports a bare func(x) call"
            )
            if engine == "native":
                raise ValueError(f"engine='native' requested but not eligible: {reason}")
            _log(verbose, "series", "pandas", reason)

        if progress_bar:
            func = with_progress(func, total=len(series), label="turboply")
        return series.apply(func, *args, **kwargs)

    apply = __call__


@pd.api.extensions.register_dataframe_accessor("turboply")
class TurboplyDataFrameAccessor:
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    def __call__(self, func, *args, engine="auto", verbose=False, progress_bar=False, axis=0, **kwargs):
        _check_engine(engine)
        df = self._obj
        no_extra_args = not args and not kwargs
        is_row_wise = axis in (1, "columns")

        if engine != "pandas" and is_row_wise and no_extra_args:
            decision = decide_row.decide(df, func, enforce_min_rows=(engine != "native"))
            _log(verbose, "dataframe", decision.engine, decision.reason)
            if decision.result is not None:
                return decision.result
            if engine == "native":
                raise ValueError(f"engine='native' requested but not eligible: {decision.reason}")

            parallel_result = parallel.try_parallel_fallback(df, func, axis=1)
            _parallel_decision_log(verbose, "dataframe", parallel_result)
            if parallel_result is not None:
                return parallel_result
        else:
            if engine == "native":
                reason = "no fast path for axis=0 (column-wise) yet" if not is_row_wise else "extra args/kwargs passed"
                raise ValueError(f"engine='native' requested but not eligible: {reason}")
            reason = "engine='pandas' forced" if engine == "pandas" else "no native or parallel fast path applies"
            _log(verbose, "dataframe", "pandas", reason)

        if progress_bar:
            total = len(df) if is_row_wise else len(df.columns)
            func = with_progress(func, total=total, label="turboply")
        return df.apply(func, *args, axis=axis, **kwargs)

    apply = __call__


class _CachedGroupByAccessor:
    """Reimplements pandas' own accessor-descriptor pattern (caches the
    accessor instance on the owning object after first access, same as
    pandas.core.accessor.CachedAccessor) locally rather than importing it.

    pandas.api.extensions has register_series_accessor/
    register_dataframe_accessor/register_index_accessor, but no
    register_*_groupby_accessor — DataFrameGroupBy/SeriesGroupBy have no
    first-class accessor-registration API to hook into, so this attaches
    the descriptor directly via setattr() on those classes instead."""

    def __init__(self, name, accessor):
        self._name = name
        self._accessor = accessor

    def __get__(self, obj, cls):
        if obj is None:
            return self._accessor
        accessor_obj = self._accessor(obj)
        object.__setattr__(obj, self._name, accessor_obj)
        return accessor_obj


class TurboplyGroupByAccessor:
    """`.turboply` on the result of `.groupby(...)` — DataFrameGroupBy or
    SeriesGroupBy alike, since both just need `.apply(func, *args,
    **kwargs)` delegated through unchanged; what differs between them
    (whether func receives a sub-DataFrame or sub-Series per group) is
    entirely pandas' own concern, not this accessor's.

    No native fast path exists for GroupBy yet — this always delegates to
    plain GroupBy.apply(), so it's correctness-equivalent to it by
    construction (the same starting point every other accelerated tier in
    this project began from, per decide.py's docstring, before any native
    path was trusted to slot in behind it). `engine="native"` raises
    rather than silently running the (currently nonexistent) fast path,
    the same reason-carrying error the Series/DataFrame accessors raise
    for their own ineligible cases."""

    def __init__(self, groupby_obj):
        self._obj = groupby_obj

    def __call__(self, func, *args, engine="auto", verbose=False, progress_bar=False, **kwargs):
        _check_engine(engine)
        if engine == "native":
            raise ValueError("engine='native' requested but not eligible: no native GroupBy fast path implemented yet")
        reason = "engine='pandas' forced" if engine == "pandas" else "no native GroupBy fast path implemented yet"
        _log(verbose, "groupby", "pandas", reason)

        if progress_bar:
            func = with_progress(func, total=self._obj.ngroups, label="turboply")
        return self._obj.apply(func, *args, **kwargs)

    apply = __call__


DataFrameGroupBy.turboply = _CachedGroupByAccessor("turboply", TurboplyGroupByAccessor)
SeriesGroupBy.turboply = _CachedGroupByAccessor("turboply", TurboplyGroupByAccessor)
