$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Cài uv: https://docs.astral.sh/uv/getting-started/installation/' }
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'uv sync thất bại' }
$localDotnet = Join-Path $env:USERPROFILE '.dotnet/dotnet.exe'
$sdk = if (Test-Path -LiteralPath $localDotnet) { $localDotnet } else { 'dotnet' }
& $sdk restore HoneycombStudio.sln --locked-mode
if ($LASTEXITCODE -ne 0) { throw 'Cần .NET SDK 10.0.402 (x64), Internet/NuGet và Windows SDK build tools' }
& $sdk build HoneycombStudio.sln -c Release -p:Platform=x64 --no-restore
if ($LASTEXITCODE -ne 0) { throw 'Build WinUI thất bại' }
Write-Host 'Sẵn sàng. Chạy scripts/start-app.ps1'
