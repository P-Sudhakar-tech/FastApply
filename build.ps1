# Local dev build fallback for machines where the precompiled maturin.exe
# can't run (e.g. missing Visual C++ Redistributable / Universal CRT, while
# only the GNU Rust toolchain is installed). Does what `maturin develop`
# would do: compile the cdylib and drop it into the package as a .pyd.
#
# Prefer `maturin develop --release` when it works on your machine; this is
# the fallback.

$ErrorActionPreference = "Stop"

cargo build --release
Copy-Item -Force "target\release\_turboply.dll" "python\turboply\_turboply.pyd"

Write-Host "Built python\turboply\_turboply.pyd"
Write-Host "Run tests with: `$env:PYTHONPATH='python'; .venv\Scripts\python.exe -m pytest -v"
