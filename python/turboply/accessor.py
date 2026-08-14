"""pandas accessor: numeric fast path (Phase 2) with a pandas-equivalent
fallback for everything else.

`.turboply.apply()` first checks whether the call is eligible for the
native numeric fast path (see decide.py) and, if so, dispatches to it.
Anything not recognized as safe falls back to plain `pandas.apply()`, so
the accessor is always correctness-equivalent to it.
"""

import pandas as pd

from . import decide


@pd.api.extensions.register_series_accessor("turboply")
class TurboplySeriesAccessor:
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    def apply(self, func, *args, **kwargs):
        if not args and not kwargs:
            fast = decide.try_numeric_fast_path(self._obj, func)
            if fast is not None:
                return fast
        return self._obj.apply(func, *args, **kwargs)


@pd.api.extensions.register_dataframe_accessor("turboply")
class TurboplyDataFrameAccessor:
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    def apply(self, func, *args, **kwargs):
        return self._obj.apply(func, *args, **kwargs)
