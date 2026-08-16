# Turboply

A drop-in, accelerated replacement for `pandas.apply()`, in the spirit of
[swifter](https://github.com/jmcarpenter2/swifter).

Status: **Phase 4** — numeric transforms detected as linear/abs (e.g.
`x * 2 + 1`) and whitelisted string methods (`str.upper`/`.lower`/`.strip`,
plus `.turboply.str.contains()`/`.replace()`) run through a native fast
path, ~1.9–2x faster than plain `pandas.apply()` on 1,000 rows
(`examples/benchmark.py`). Arbitrary callables that don't qualify get a
sampling-based threaded fallback that only engages when actually measured
faster (helps I/O-bound work, correctly declines pure-CPU-bound Python).
Everything else falls back to native `pandas.apply()`, so `.turboply` is
always correctness-equivalent to it. See `claude.md` for the full roadmap.

## Development

The native extension is built with [PyO3](https://pyo3.rs) +
[maturin](https://www.maturin.rs).

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install maturin pytest pandas numpy
maturin develop                # builds the extension and installs it in the venv
pytest -v
```

If `maturin develop` fails to launch on your machine (e.g. `maturin.exe`
can't load `api-ms-win-crt-*.dll` because only the GNU Rust toolchain is
installed and the MSVC Visual C++ Redistributable is missing), use the
fallback build script instead. It calls `cargo build` directly, drops the
resulting DLL into the package as a `.pyd`, and links `python/` into the
venv via a `.pth` file (same end result as `maturin develop`, so
`import turboply` works from anywhere without setting `PYTHONPATH`):

```powershell
./build.ps1
.venv/Scripts/python.exe -m pytest -v
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on Ubuntu with a
properly provisioned toolchain, so `maturin develop` works there regardless.

## Usage

The accessor is directly callable — `s.turboply(func)` is the primary API,
not `s.turboply.apply(func)` (kept only as an alias):

```python
import pandas as pd
import turboply  # registers the .turboply accessor

s = pd.Series([1, 2, 3])
s.turboply(lambda x: x * 2)   # identical result to s.apply(lambda x: x * 2)

df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
df.turboply(lambda row: row["a"] + row["b"], axis=1)

# Whitelisted string methods run through the native path too:
names = pd.Series(["  Ada  ", "GRACE", "margaret"] * 50)
names.turboply(str.upper)
names.turboply(str.strip)

# Regex-backed ops mirror pandas' own .str accessor (called directly,
# not inferred from a lambda — see claude.md for why):
names.turboply.str.contains(r"^GRACE$")
names.turboply.str.replace(r"\s+", "_")
```

### Options

```python
s.turboply(func, engine="auto")     # default: try the native fast path, fall back silently
s.turboply(func, engine="pandas")   # always plain pandas .apply(), skips the eligibility check
s.turboply(func, engine="native")   # require the fast path; raises ValueError with the
                                     # specific reason if func isn't eligible, instead of
                                     # silently falling back

s.turboply(func, verbose=True)      # prints which engine was used and why, to stderr

s.turboply(func, progress_bar=True) # progress bar for the pandas-fallback path only —
                                     # the native path is one vectorized call, nothing to
                                     # report progress on there
```

## Benchmarks

`examples/benchmark.py` compares plain `pandas.apply()` against `.turboply()`
on 1,000 rows (median of 50 runs, 5 warmup): the numeric-transform case
(`x * 2 + 1`) lands at **~1.9–2x**, since it's eligible for the native fast
path; row-wise `DataFrame.apply` is unchanged pandas fallback unless a
threaded-parallel win is measured (Phase 3) — there's no native DataFrame
fast path yet (that's Phase 5).

`examples/benchmark_vs_swifter.py` adds a comparison against
[swifter](https://github.com/jmcarpenter2/swifter)'s `.apply()`. It's a
separate opt-in script (not a `turboply` dependency) since swifter pulls in
dask, tqdm, etc. As of this writing swifter 1.4.0 doesn't run cleanly against
recent pandas/Python — see that script's error message for the specific
compatibility gap if you hit it.
