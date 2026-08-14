"""Phase 1: pandas accessor with a 100% pandas-equivalent fallback path.

No accelerated dispatch happens yet. The goal of this phase is only to get
the `.turboply` interface correct and provably identical to plain
`.apply()` before any acceleration is layered on top in later phases.
"""

import pandas as pd


@pd.api.extensions.register_series_accessor("turboply")
class TurboplySeriesAccessor:
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    def apply(self, func, *args, **kwargs):
        return self._obj.apply(func, *args, **kwargs)


@pd.api.extensions.register_dataframe_accessor("turboply")
class TurboplyDataFrameAccessor:
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    def apply(self, func, *args, **kwargs):
        return self._obj.apply(func, *args, **kwargs)
