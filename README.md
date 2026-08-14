# Turboply

A drop-in, accelerated replacement for `pandas.apply()`, in the spirit of
[swifter](https://github.com/jmcarpenter2/swifter).

Status: **Phase 0/1** — the `.turboply` accessor exists and always falls back
to native `pandas.apply()`. No accelerated dispatch is wired up yet; see
`claude.md` for the full roadmap.

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
fallback build script instead, which calls `cargo build` directly and drops
the resulting DLL into the package as a `.pyd`:

```powershell
./build.ps1
$env:PYTHONPATH = "python"
.venv/Scripts/python.exe -m pytest -v
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs on Ubuntu with a
properly provisioned toolchain, so `maturin develop` works there regardless.

## Usage

```python
import pandas as pd
import turboply  # registers the .turboply accessor

s = pd.Series([1, 2, 3])
s.turboply.apply(lambda x: x * 2)   # identical result to s.apply(lambda x: x * 2)

df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
df.turboply.apply(lambda row: row["a"] + row["b"], axis=1)
```
