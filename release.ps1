# Publish a new version: bumps acctmgr/version.py, writes release notes, commits, tags and pushes.
# GitHub Actions then builds the exe and creates the Release; running programs update themselves.
#
# Usage:  .\release.ps1 -Version 1.0.1 -Notes "fixed X; added Y"
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Notes
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like 1.2.3" }
$current = python -c "from acctmgr.version import __version__; print(__version__)"
if ([version]$Version -le [version]$current) { throw "New version $Version must be greater than current $current" }
if (git status --porcelain) { Write-Host "Uncommitted changes will be included in this release:"; git status --short }

$utf8 = New-Object System.Text.UTF8Encoding($false)
$vfile = "acctmgr\version.py"
$text = [IO.File]::ReadAllText("$PSScriptRoot\$vfile", $utf8) -replace '__version__ = "[^"]+"', "__version__ = `"$Version`""
[IO.File]::WriteAllText("$PSScriptRoot\$vfile", $text, $utf8)
[IO.File]::WriteAllText("$PSScriptRoot\RELEASE_NOTES.md", ($Notes -replace ';\s*', "`n- ").Insert(0, "- ") + "`n", $utf8)

git add -A
git commit -m "Release v$Version"
git tag "v$Version"
git push origin HEAD
git push origin "v$Version"
Write-Host "Pushed v$Version. Build progress: gh run watch  (or the Actions tab on GitHub)"
