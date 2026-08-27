"""Sampling-based threaded parallel fallback for GroupBy.apply() — same
measured-not-assumed philosophy as parallel.py's Series/DataFrame axis=1
fallback (Phase 3), adapted for groups instead of contiguous row ranges.

A GroupBy object can't be chunked by row range the way a Series/DataFrame
can (there's no slicing that preserves grouping semantics), so this
chunks by GROUP instead: run the real `func` on every group in worker
threads first (the expensive part), collect the results in the same
order the groupby object itself visits groups in, then hand those
precomputed results to a cheap, single-threaded pass back through the
REAL `GroupBy.apply()` — passing a stand-in function that just returns
each precomputed result in turn instead of recomputing it. That second
pass is what actually produces pandas' exact result shape (scalar-per-
group -> Series, DataFrame-per-group -> concatenated with group keys as
an index level, respecting group_keys/as_index/sort/dropna, etc.) with
zero custom reimplementation of that combination logic — and therefore
zero risk of it drifting from a given pandas version's own rules. Both
passes iterate the SAME already-constructed groupby object, so they see
the same groups in the same order deterministically (the grouper is
computed once and cached on the object, not re-derived per iteration).

The one case this declines outright rather than risk being wrong:
`include_groups=False` (DataFrameGroupBy.apply()-only) strips the
grouping columns from each group before `func` sees it — but plain
iteration over the groupby object does NOT do that stripping, so a
pre-pass built from direct iteration would call `func` on the wrong
shape of group whenever include_groups is in play. Rather than
reimplement pandas' own column-stripping rule, this tier just doesn't
engage at all when `include_groups` is passed (of either value), and
the caller falls back to plain serial GroupBy.apply() instead — safe,
just not accelerated for that call.
"""

import itertools
import os
import time
from concurrent.futures import ThreadPoolExecutor

MIN_GROUPS = 20
SAMPLE_GROUPS = 8
MIN_SPEEDUP = 1.5
_MIN_MEASURABLE_TIME = 0.001
_MAX_WORKERS = min(32, os.cpu_count() or 4)


def _call(func, group, args, kwargs):
    return func(group, *args, **kwargs)


def _time_once(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _run_serial(groups, func, args, kwargs):
    return [_call(func, g, args, kwargs) for g in groups]


def _run_threaded(groups, func, args, kwargs):
    if not groups:
        return []
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(groups))) as pool:
        futures = [pool.submit(_call, func, g, args, kwargs) for g in groups]
        return [f.result() for f in futures]


def try_parallel_fallback(groupby_obj, func, args, kwargs):
    """Return an accelerated result equivalent to
    groupby_obj.apply(func, *args, **kwargs), or None if a sample
    measurement didn't show threading actually helps (or the call isn't
    eligible at all) — caller should fall back to plain serial
    GroupBy.apply() in that case."""
    if "include_groups" in kwargs:
        return None

    n_groups = groupby_obj.ngroups
    if n_groups < MIN_GROUPS:
        return None

    sample = [g for _, g in itertools.islice(groupby_obj, SAMPLE_GROUPS)]
    if not sample:
        return None

    try:
        t_serial = _time_once(lambda: _run_serial(sample, func, args, kwargs))
        if t_serial < _MIN_MEASURABLE_TIME:
            return None
        t_parallel = _time_once(lambda: _run_threaded(sample, func, args, kwargs))
    except Exception:
        return None

    if t_parallel <= 0 or t_serial / t_parallel < MIN_SPEEDUP:
        return None

    try:
        all_groups = [g for _, g in groupby_obj]
        precomputed = _run_threaded(all_groups, func, args, kwargs)
    except Exception:
        return None

    results = iter(precomputed)

    def _replay(_group, *_args, **_kwargs):
        return next(results)

    try:
        return groupby_obj.apply(_replay, *args, **kwargs)
    except Exception:
        return None
