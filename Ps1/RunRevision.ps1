param(
    [string]$Config='Json/Config/Workflow.json',
    [string]$ProPython='C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat',
    [string]$CredentialPath,
    [int]$MaximumAttempts=12,
    [int]$RetrySeconds=300
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
if ($CredentialPath) { $env:ENVERUS_CREDENTIAL_PATH=$CredentialPath }
$configPath=if ([IO.Path]::IsPathRooted($Config)) {$Config} else {Join-Path $taskRoot $Config}
$cfg=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$folder=Join-Path $taskRoot ('Log\'+$cfg.profile)
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$state=Join-Path $folder 'RevisionWorker.json'
function Write-State([string]$Phase,[int]$Code) {
    @{phase=$Phase;exitCode=$Code;processId=$PID;updated=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
}
for ($attempt=1;$attempt -le $MaximumAttempts;$attempt++) {
    Write-State 'SyncAndHeaderBackfill' 0
    $ErrorActionPreference='Continue'
    & $ProPython (Join-Path $taskRoot 'Py\BuildEnverusGuggWellRecord.py') sync --config $Config 2>&1 | Tee-Object -FilePath (Join-Path $folder ('RevisionSyncAttempt'+$attempt+'.log'))
    $code=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    if ($code -eq 0) { break }
    if ($code -eq 75) { Write-State 'AnotherRunActive' $code;exit $code }
    Write-State 'WaitingToRetrySync' $code
    if ($attempt -lt $MaximumAttempts) { Start-Sleep -Seconds $RetrySeconds }
}
if ($code -ne 0) { Write-State 'SyncNeedsAttention' $code;exit $code }
Write-State 'MigratingProductRegistry' 0
$ErrorActionPreference='Continue'
& $ProPython (Join-Path $taskRoot 'Py\BuildEnverusGuggWellRecord.py') migrate --config $Config 2>&1 | Tee-Object -FilePath (Join-Path $folder 'RevisionMigration.log')
$code=$LASTEXITCODE
$ErrorActionPreference='Stop'
if ($code -ne 0) { Write-State 'MigrationNeedsAttention' $code;exit $code }
Write-State 'BuildingAndPackagingThreeProducts' 0
$ErrorActionPreference='Continue'
& $ProPython (Join-Path $taskRoot 'Py\CacheTransfer.py') export --config $Config --include-gis --build-gis-first 2>&1 | Tee-Object -FilePath (Join-Path $folder 'RevisionBuildTransfer.log')
$code=$LASTEXITCODE
$ErrorActionPreference='Stop'
Write-State $(if($code -eq 0){'Complete'}else{'BuildOrTransferNeedsAttention'}) $code
exit $code
