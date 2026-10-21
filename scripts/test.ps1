$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
uv run --locked ruff check src tests scripts
if ($LASTEXITCODE -ne 0) { throw 'Lint failed' }
uv run --locked ty check src/honeycomb_studio --exclude src/honeycomb_studio/adapters
if ($LASTEXITCODE -ne 0) { throw 'Type check failed' }
uv run --locked pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Python tests failed' }
$localDotnet = Join-Path $env:USERPROFILE '.dotnet/dotnet.exe'
$sdk = if (Test-Path -LiteralPath $localDotnet) { $localDotnet } else { 'dotnet' }
& $sdk test tests/Desktop.Tests/Desktop.Tests.csproj -c Release
if ($LASTEXITCODE -ne 0) { throw 'C# tests failed' }
& $sdk build desktop/HoneycombStudio/HoneycombStudio.csproj -c Release -p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
