$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo 'desktop/HoneycombStudio/bin/x64/Release/net10.0-windows10.0.19041.0/win-x64/HoneycombStudio.exe'
if (-not (Test-Path -LiteralPath $exe)) { & (Join-Path $PSScriptRoot 'setup.ps1') }
Start-Process -FilePath $exe -WorkingDirectory $repo
