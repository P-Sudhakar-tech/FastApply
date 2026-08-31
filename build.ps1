# Local dev build fallback for machines where the precompiled maturin.exe
# can't run (e.g. missing Visual C++ Redistributable / Universal CRT, while
# only the GNU Rust toolchain is installed). Does what `maturin develop`
# would do: compile the cdylib, drop it into the package as a .pyd, and
# point the venv at the repo root via a .pth file so `import turbofastapply`
# works from anywhere without setting PYTHONPATH.
#
# Prefer `maturin develop --release` when it works on your machine; this is
# the fallback.

$ErrorActionPreference = "Stop"

cargo build --release
Copy-Item -Force "target\release\_turbofastapply.dll" "turbofastapply\_turbofastapply.pyd"

$sitePackages = & .venv\Scripts\python.exe -c "import site; print(site.getsitepackages()[-1])"
$repoRoot = (Resolve-Path ".").Path
$pthPath = Join-Path $sitePackages "turbofastapply.pth"
[System.IO.File]::WriteAllText($pthPath, $repoRoot, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Built turbofastapply\_turbofastapply.pyd"
Write-Host "Linked $repoRoot into the venv via turbofastapply.pth"
Write-Host "Run tests with: .venv\Scripts\python.exe -m pytest -v"
