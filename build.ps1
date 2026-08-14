# Local dev build fallback for machines where the precompiled maturin.exe
# can't run (e.g. missing Visual C++ Redistributable / Universal CRT, while
# only the GNU Rust toolchain is installed). Does what `maturin develop`
# would do: compile the cdylib, drop it into the package as a .pyd, and
# point the venv at python/ via a .pth file so `import turboply` works
# from anywhere without setting PYTHONPATH.
#
# Prefer `maturin develop --release` when it works on your machine; this is
# the fallback.

$ErrorActionPreference = "Stop"

cargo build --release
Copy-Item -Force "target\release\_turboply.dll" "python\turboply\_turboply.pyd"

$sitePackages = & .venv\Scripts\python.exe -c "import site; print(site.getsitepackages()[-1])"
$pythonSrc = (Resolve-Path "python").Path
$pthPath = Join-Path $sitePackages "turboply.pth"
[System.IO.File]::WriteAllText($pthPath, $pythonSrc, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Built python\turboply\_turboply.pyd"
Write-Host "Linked $pythonSrc into the venv via turboply.pth"
Write-Host "Run tests with: .venv\Scripts\python.exe -m pytest -v"
