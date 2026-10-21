param([switch]$EngineOnly)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskPackage = Join-Path $taskRepo 'artifacts/HoneycombStudio-v0.2.0-win-x64'
if (-not (Test-Path -LiteralPath (Join-Path $taskPackage 'runtime/python.exe'))) {
    $taskPackage = Join-Path $taskRepo 'artifacts/HoneycombStudio-win-x64'
}
$taskExe = Join-Path $taskPackage 'HoneycombStudio.exe'
$taskPython = Join-Path $taskPackage 'runtime/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path $taskRepo '.venv/Scripts/python.exe'
    $taskExe = Join-Path $taskRepo 'desktop/HoneycombStudio/bin/x64/Release/net10.0-windows10.0.19041.0/win-x64/HoneycombStudio.exe'
}
if (-not (Test-Path -LiteralPath $taskPython) -or -not (Test-Path -LiteralPath $taskExe)) {
    throw 'Run scripts/setup.ps1 or scripts/publish.ps1 first.'
}
$taskConfig = Join-Path $env:LOCALAPPDATA 'HoneycombStudio'
$taskSettingsFile = Join-Path $taskConfig 'engine-settings.json'
$taskSettings = @{data_root='C:/UET/DO_AN/honeycomb-data'; abaqus='C:/SIMULIA/Commands/abaqus.bat'}
if (Test-Path -LiteralPath $taskSettingsFile) {
    $taskSettings = Get-Content -LiteralPath $taskSettingsFile -Raw | ConvertFrom-Json
}
foreach ($taskValue in @($taskSettings.data_root, $taskSettings.abaqus)) {
    if ($taskValue -match '["\r\n]') { throw 'Invalid path in engine settings.' }
}
# A normal child process (even with no console) can inherit ChatGPT's Job Object.
# Demand-only tasks are owned by Windows Task Scheduler instead of the chat host.
# There are deliberately no triggers, login startup or elevated privileges.
$taskService = New-Object -ComObject 'Schedule.Service'
$taskService.Connect()
$taskFolder = $taskService.GetFolder('\')
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
function Register-DemandTask([string]$Name, [string]$Executable, [string]$Arguments, [bool]$Background) {
    $taskDefinition = $taskService.NewTask(0)
    $taskDefinition.RegistrationInfo.Description = 'Honeycomb Studio independent on-demand process; no automatic triggers.'
    $taskDefinition.Principal.UserId = $taskUser
    $taskDefinition.Principal.LogonType = 3 # Existing interactive user token, no stored password.
    $taskDefinition.Principal.RunLevel = 0
    $taskDefinition.Settings.ExecutionTimeLimit = 'PT0S'
    $taskDefinition.Settings.MultipleInstances = 2 # Ignore a duplicate start.
    $taskDefinition.Settings.DisallowStartIfOnBatteries = $false
    $taskDefinition.Settings.StopIfGoingOnBatteries = $false
    if ($Background) {
        $taskDefinition.Settings.RestartCount = 3
        $taskDefinition.Settings.RestartInterval = 'PT1M'
    }
    $taskAction = $taskDefinition.Actions.Create(0)
    $taskAction.Path = $Executable
    $taskAction.Arguments = $Arguments
    $taskAction.WorkingDirectory = $taskRepo
    return $taskFolder.RegisterTaskDefinition($Name, $taskDefinition, 6, $null, $null, 3)
}
$taskPythonWindowless = Join-Path (Split-Path -Parent $taskPython) 'pythonw.exe'
if (Test-Path -LiteralPath $taskPythonWindowless) { $taskPython = $taskPythonWindowless }
$taskEntry = Join-Path $PSScriptRoot 'independent_engine.py'
$taskEngine = Register-DemandTask 'HoneycombStudio-Engine' $taskPython ('-X utf8 "'+$taskEntry+'" serve --data-root "'+$taskSettings.data_root+'" --abaqus "'+$taskSettings.abaqus+'"') $true
$taskSessionFile = Join-Path $taskConfig 'session.json'
$taskConnected = $false
if (Test-Path -LiteralPath $taskSessionFile) {
    try {
        $taskSession = Get-Content -LiteralPath $taskSessionFile -Raw | ConvertFrom-Json
        $taskHealth = Invoke-RestMethod ($taskSession.url+'/health') -TimeoutSec 2
        $taskConnected = $taskHealth.service -eq 'honeycomb-studio'
    } catch { }
}
if (-not $taskConnected -and $taskEngine.State -ne 4) { $taskEngine.Run($null) | Out-Null }
if (-not $EngineOnly) {
    $taskUi = Register-DemandTask 'HoneycombStudio-UI' $taskExe '' $false
    if ($taskUi.State -ne 4) { $taskUi.Run($null) | Out-Null }
}
Write-Host 'Honeycomb started independently through Windows (on demand; no schedule).'
