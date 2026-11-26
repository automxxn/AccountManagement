# Build AccountManagement.exe (used locally and by GitHub Actions)
# Output: dist\AccountManagement.exe, dist\AccountManagement.exe.sha256
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name AccountManagement `
    --icon assets/app.ico `
    --collect-submodules acctmgr `
    run_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$hash = (Get-FileHash "dist\AccountManagement.exe" -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$PSScriptRoot\dist\AccountManagement.exe.sha256", $hash)
Write-Host "Built dist\AccountManagement.exe ($hash)"
