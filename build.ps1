# Build AccountManagement.exe (used locally and by GitHub Actions)
# Output: dist\AccountManagement.exe, dist\AccountManagement.exe.sha256
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 배포용 연결 정보 (GitHub Secrets → 환경 변수). 저장소에는 올리지 않는 파일로 만든다.
$gen = "$PSScriptRoot\acctmgr\_build_defaults.py"
if ($env:SUPABASE_URL -and $env:SUPABASE_ANON_KEY) {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $py = "SUPABASE_URL = '" + $env:SUPABASE_URL.Trim() + "'`nSUPABASE_ANON_KEY = '" + $env:SUPABASE_ANON_KEY.Trim() + "'`n"
    [IO.File]::WriteAllText($gen, $py, $utf8)
    Write-Host "Built-in connection settings: included"
} else {
    if (Test-Path $gen) { Remove-Item $gen }
    Write-Host "Built-in connection settings: none (users will see the connection dialog)"
}

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name AccountManagement `
    --icon assets/app.ico `
    --collect-submodules acctmgr `
    run_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$hash = (Get-FileHash "dist\AccountManagement.exe" -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$PSScriptRoot\dist\AccountManagement.exe.sha256", $hash)
Write-Host "Built dist\AccountManagement.exe ($hash)"
