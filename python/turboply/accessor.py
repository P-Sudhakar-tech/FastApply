"""pandas accessor: numeric fast path (Phase 2) with a pandas-equivalent
fallback for everything else, plus Phase 6 UX polish — engine selection,
verbose routing explanations, and an optional progress bar for whichever
path ends up doing a row-by-row Python loop.

The accessor is directly callable — `s.turboply(func)` — instead of
requiring the `.apply()` method name. `.apply()` is kept as an alias for
readers coming from `pandas.apply()`, but the direct-call form is the
primary, documented API.

`engine`:
  - "auto" (default) — try the native fast path, silently fall back to
    pandas if the callable isn't eligible.
  - "native" — require the native fast path; raises ValueError with the
    specific reason if the callable isn't eligible, instead of silently
    falling back. There's no DataFrame fast path yet, so this always
    raises on the DataFrame accessor.
  - "pandas" — skip the eligibility check entirely and always use plain
    pandas .apply(), including its per-call probing/sampling overhead.

`verbose=True` prints which engine was chosen and why to stderr.
`progress_bar=True` reports progress for the pandas fallback path only —
the native path is a single vectorized call, so there's no per-row
progress to report there.
"""

import sys

import pandas as pd

from . import decide
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
        reason = "no DataFrame fast path yet (see roadmap Phase 5)"
        if engine == "native":
            raise ValueError(f"engine='native' requested but not eligible: {reason}")
        _log(verbose, "dataframe", "pandas", reason)

        df = self._obj
        if progress_bar:
            total = len(df) if axis in (1, "columns") else len(df.columns)
            func = with_progress(func, total=total, label="turboply")
        return df.apply(func, *args, axis=axis, **kwargs)

    apply = __call__
