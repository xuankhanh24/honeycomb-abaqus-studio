param([string]$DataRoot = 'C:/UET/DO_AN/honeycomb-data', [string]$Abaqus = 'C:/SIMULIA/Commands/abaqus.bat')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
uv run --locked honeycomb-studio serve --data-root $DataRoot --abaqus $Abaqus
