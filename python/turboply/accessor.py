"""pandas accessor: numeric fast path (Phase 2), sampling-based parallel
fallback for arbitrary callables (Phase 3), and a pandas-equivalent
fallback for everything else — plus Phase 6 UX polish: engine selection,
verbose routing explanations, and an optional progress bar for whichever
path ends up doing a row-by-row Python loop.

The accessor is directly callable — `s.turboply(func)` — instead of
requiring the `.apply()` method name. `.apply()` is kept as an alias for
readers coming from `pandas.apply()`, but the direct-call form is the
primary, documented API.

Three tiers are tried in order under `engine="auto"`:
  1. Native numeric fast path (decide.py) — vectorized, single call.
  2. Threaded parallel fallback (parallel.py) — only engages when a
     sample measurement shows it's actually faster than serial (true for
     I/O-bound or otherwise GIL-releasing callables; a no-op for
     CPU-bound pure Python, which the GIL prevents from parallelizing).
  3. Plain pandas .apply().

`engine`:
  - "auto" (default) — try tiers 1 and 2, silently fall back to plain
    pandas if neither is eligible.
  - "native" — require tier 1; raises ValueError with the specific reason
    if the callable isn't eligible. There's no DataFrame fast path yet,
    so this always raises on the DataFrame accessor.
  - "pandas" — skip tiers 1 and 2 entirely and always use plain pandas
    .apply().

`verbose=True` prints which tier was chosen and why to stderr.
`progress_bar=True` reports progress for the pandas fallback path only —
the native and threaded-parallel paths don't do a single-threaded
row-by-row loop, so there's no equivalent per-row progress to report for
them.
"""

import sys

import pandas as pd

from . import decide, parallel
from .progress import with_progress

_ENGINES = ("auto", "native", "pandas")


def _check_engine(engine):
    if engine not in _ENGINES:
        raise ValueError(f"engine must be one of {_ENGINES}, got {engine!r}")


def _log(verbose, label, engine, reason):
    if verbose:
        print(f"[turboply] {label}: engine={engine} - {reason}", file=sys.stderr)


@pd.api.extensions.register_series_accessor("turboply")
class TurboplySeriesAccessor:
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    def __call__(self, func, *args, engine="auto", verbose=False, progress_bar=False, **kwargs):
        _check_engine(engine)
        series = self._obj
        no_extra_args = not args and not kwargs

        if engine != "pandas" and no_extra_args:
            decision = decide.decide(series, func)
            _log(verbose, "series", decision.engine, decision.reason)
            if decision.result is not None:
                return decision.result
            if engine == "native":
                raise ValueError(f"engine='native' requested but not eligible: {decision.reason}")

            parallel_result = parallel.try_parallel_fallback(series, func)
            if parallel_result is not None:
                _log(
                    verbose,
                    "series",
                    "threaded-parallel",
                    f"sample of {parallel.SAMPLE_ROWS} rows measured >= "
                    f"{parallel.MIN_SPEEDUP}x faster threaded than serial",
                )
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
        if engine == "native":
            raise ValueError(
                "engine='native' requested but not eligible: no DataFrame fast path yet (see roadmap Phase 5)"
            )

        df = self._obj
        no_extra_args = not args and not kwargs
        is_row_wise = axis in (1, "columns")

        if engine == "auto" and is_row_wise and no_extra_args:
            parallel_result = parallel.try_parallel_fallback(df, func, axis=1)
            if parallel_result is not None:
                _log(
                    verbose,
                    "dataframe",
                    "threaded-parallel",
                    f"sample of {parallel.SAMPLE_ROWS} rows measured >= "
                    f"{parallel.MIN_SPEEDUP}x faster threaded than serial",
                )
                return parallel_result
            _log(verbose, "dataframe", "pandas", "no native fast path yet, sample showed no threading benefit")
        else:
            reason = "engine='pandas' forced" if engine == "pandas" else "no native or parallel fast path applies"
            _log(verbose, "dataframe", "pandas", reason)

        if progress_bar:
            total = len(df) if is_row_wise else len(df.columns)
            func = with_progress(func, total=total, label="turboply")
        return df.apply(func, *args, axis=axis, **kwargs)

    apply = __call__
