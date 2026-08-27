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
import threading
import time
from concurrent.futures import ThreadPoolExecutor

MIN_GROUPS = 800
SAMPLE_GROUPS = 8
MIN_SPEEDUP = 1.5
_MIN_MEASURABLE_TIME = 0.001
_MAX_WORKERS = min(32, os.cpu_count() or 4)
_SAMPLE_REPEATS = 5

# Why MIN_GROUPS is 800, not a smaller "feels reasonable" number: the
# unanimous-across-repeats check below needs _SAMPLE_REPEATS independent
# (serial, threaded) measurements to reliably tell a genuine GIL-releasing
# speedup apart from timing noise (see the comment on that check). That
# means every call -- even one that correctly ends up declining -- pays a
# fixed cost of roughly SAMPLE_GROUPS * (1 + 2 * _SAMPLE_REPEATS) group-
# equivalent evaluations for measurement alone. Critically, this fixed
# cost is a *pure function of SAMPLE_GROUPS and _SAMPLE_REPEATS* -- it
# does NOT depend on what func actually costs per group, because that
# per-group cost cancels out of the measurement-cost-to-job-cost ratio
# (confirmed empirically, not just algebraically: measured the same
# ratio for a cheap GIL-releasing callable and an expensive CPU-bound one
# at the same n_groups). So MIN_GROUPS is the only lever that controls
# this overhead, and it has to be large enough that this fixed
# measurement tax is a small fraction of ANY real job, regardless of how
# expensive or cheap each group's real work turns out to be. Verified
# directly: at MIN_GROUPS=150, examples/benchmark_groupby.py's full
# scan (varying both group count and rows-per-group) still showed real
# regressions (down to 0.42x) for CPU-bound callables with substantial
# per-group cost, even though the parallelize/decline *decision* itself
# was correct -- the decline path's own fixed measurement overhead was
# the regression. 800 was the smallest group count in that same scan
# where CPU-bound callables landed consistently at ~0.94-0.99x (no real
# regression) across every rows-per-group tested (1 to 1000), while
# genuinely GIL-releasing callables still measured a strong, real
# 2.0-2.3x speedup at that same scale and beyond.

# A fresh ThreadPoolExecutor spawns real OS threads on every construction,
# and on Windows that cost (observed several ms) is easily larger than the
# work being measured for a small SAMPLE_GROUPS -- benchmarking a genuinely
# GIL-releasing callable (examples/benchmark_groupby.py) showed this
# swamping the sample-timing signal entirely, reporting ~1.0x instead of a
# real speedup. A single lazily-created, never-shutdown, module-level pool
# reused across both the sample-timing pass and the full-data pass (and
# across separate try_parallel_fallback calls) pays that thread-creation
# cost once per process instead of twice per call.
_executor_lock = threading.Lock()
_executor = None


def _get_executor():
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    return _executor


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
    pool = _get_executor()
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

    # A single (serial, threaded) timing pair is genuinely, and severely,
    # noisy at this scale -- a benchmark run (examples/benchmark_groupby.py)
    # caught a real ~3x regression on a CPU-bound (GIL-held) callable: a
    # single noisy sample measurement read as a false "2.58x speedup," and
    # committing the full run on that one bad reading meant paying full
    # serial cost PLUS threading/replay overhead for a workload that never
    # actually parallelizes under the GIL. A *median* across repeated
    # measurements was tried first and still let ~1 in 8 false positives
    # through empirically (40-trial sweep) -- not good enough, since the
    # cost of a false positive here is severe, not just "no gain". What
    # actually drove false positives to 0/40 in that same sweep (while
    # still catching 19/20 genuine GIL-releasing wins) is a *unanimous*
    # requirement: every one of _SAMPLE_REPEATS repeats must individually
    # clear MIN_SPEEDUP. A genuinely GIL-releasing callable shows
    # consistent speedup across repeats; a GIL-bound false positive
    # typically shows a mix of high and low readings in the same trial
    # (confirmed by inspecting the actual failing trials), which a median
    # can still average into a passing score but unanimity correctly
    # rejects.
    #
    # A second real bug, found the same way (benchmarking the full matrix,
    # not just one adversarial case): the unanimous check above still ran
    # every one of _SAMPLE_REPEATS (serial, threaded) pairs unconditionally
    # before ever checking _MIN_MEASURABLE_TIME -- so for a callable whose
    # real per-group cost is tiny (e.g. a 1-row group with a trivial
    # numeric loop), the *decline* path itself paid the full repeated
    # measurement cost first, and that alone was enough to regress a
    # genuinely fast job. Fixed by probing with a single cheap serial-only
    # sample run first and bailing out immediately if it's already too
    # fast to trust -- never even starting the threaded comparison, let
    # alone repeating it -- so the decline path stays cheap for cheap
    # workloads regardless of group count.
    try:
        t_serial_probe = _time_once(lambda: _run_serial(sample, func, args, kwargs))
        if t_serial_probe < _MIN_MEASURABLE_TIME:
            return None

        speedups = []
        for _ in range(_SAMPLE_REPEATS):
            t_serial = _time_once(lambda: _run_serial(sample, func, args, kwargs))
            t_parallel = _time_once(lambda: _run_threaded(sample, func, args, kwargs))
            speedups.append(t_serial / t_parallel if t_parallel > 0 else 0.0)
    except Exception:
        return None

    if any(s < MIN_SPEEDUP for s in speedups):
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
