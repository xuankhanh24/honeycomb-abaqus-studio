param([string]$Destination)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
if (-not $Destination) { $Destination = Join-Path $repo 'artifacts/HoneycombStudio-win-x64' }
$Destination = [IO.Path]::GetFullPath($Destination)
$localDotnet = Join-Path $env:USERPROFILE '.dotnet/dotnet.exe'
$sdk = if (Test-Path -LiteralPath $localDotnet) { $localDotnet } else { 'dotnet' }
& $sdk publish desktop/HoneycombStudio/HoneycombStudio.csproj -c Release -p:Platform=x64 -r win-x64 -o $Destination
if ($LASTEXITCODE -ne 0) { throw 'WinUI publish failed' }
$pythonInstall = Join-Path $repo '.tools/python'
uv python install 3.13.7 --install-dir $pythonInstall
if ($LASTEXITCODE -ne 0) { throw 'Managed Python installation failed' }
$managed = Get-ChildItem -LiteralPath $pythonInstall -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'python.exe') } | Select-Object -First 1
if (-not $managed) { throw 'Không tìm thấy managed Python' }
$runtime = Join-Path $Destination 'runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
# Copy wildcard intentionally uses -Path, while destructive operations never do.
Copy-Item -Path (Join-Path $managed.FullName '*') -Destination $runtime -Recurse -Force
uv export --locked --quiet --no-dev --no-emit-project --format requirements-txt --output-file '.tools/release-requirements.txt' | Out-Null
# Only this copied, application-private interpreter is modified.
uv pip install --python (Join-Path $runtime 'python.exe') --break-system-packages --require-hashes -r '.tools/release-requirements.txt'
if ($LASTEXITCODE -ne 0) { throw 'Engine dependencies installation failed' }
uv build --wheel
$wheel = Get-ChildItem -LiteralPath (Join-Path $repo 'dist') -Filter '*.whl' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
uv pip install --python (Join-Path $runtime 'python.exe') --break-system-packages --no-deps $wheel.FullName
if ($LASTEXITCODE -ne 0) { throw 'Engine wheel installation failed' }
Copy-Item -LiteralPath (Join-Path $repo 'README.md') -Destination $Destination
Copy-Item -LiteralPath (Join-Path $repo 'docs') -Destination $Destination -Recurse -Force
Write-Host "Bản độc lập: $Destination"
