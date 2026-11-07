param(
    [switch]$SyncSources,
    [string]$ProPython='C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat'
)
$ErrorActionPreference='Stop'
$runtimeRoot=Split-Path -Parent $PSScriptRoot
$logFolder=Join-Path $runtimeRoot 'Log\NorthAmerica'
New-Item -ItemType Directory -Force -Path $logFolder | Out-Null
$state=Join-Path $logFolder 'RevisionWorker.json'
function Write-State([string]$Phase,[int]$Code) {
    @{phase=$Phase;exitCode=$Code;processId=$PID;updated=(Get-Date).ToUniversalTime().ToString('o');runtime=$runtimeRoot} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
}
function Run-Step([string]$Phase,[string]$Script,[string[]]$StepArgs,[string]$LogName) {
    Write-State $Phase 0
    $ErrorActionPreference='Continue'
    & $ProPython (Join-Path $runtimeRoot ('Py\'+$Script)) @StepArgs 2>&1 | Tee-Object -FilePath (Join-Path $logFolder $LogName)
    $code=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    if ($code -ne 0) {Write-State ($Phase+'NeedsAttention') $code;throw "$Phase failed with exit code $code; see $LogName"}
}
try {
    if ($SyncSources) {Run-Step -Phase 'SyncAndHeaderBackfill' -Script 'BuildEnverusGuggWellRecord.py' -StepArgs @('sync') -LogName 'RevisionSyncAttempt1.log'}
    Run-Step -Phase 'ReconcilingPermitStatusScope' -Script 'ReconcileWellScope.py' -StepArgs @() -LogName 'RevisionStatusScope.log'
    Run-Step -Phase 'UpdatingContextDatasets' -Script 'ContextLayers.py' -StepArgs @('run') -LogName 'RevisionContext.log'
    Run-Step -Phase 'BuildingNationalWells' -Script 'BuildEnverusGuggWellRecord.py' -StepArgs @('build') -LogName 'RevisionBuildTransfer.log'
    Run-Step -Phase 'ValidatingNationalOutputs' -Script 'ValidateNationalOutputs.py' -StepArgs @() -LogName 'RevisionValidation.log'
    Write-State 'Complete' 0
} catch {Write-Error $_;exit 1}
