param(
    [string]$Config = 'Json/Config/Workflow.json',
    [string]$ProPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat',
    [string]$CredentialPath,
    [int]$MaximumAttempts = 12,
    [int]$RetrySeconds = 300
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if ($CredentialPath) { $env:ENVERUS_CREDENTIAL_PATH = $CredentialPath }
$configPath=if ([IO.Path]::IsPathRooted($Config)) {$Config} else {Join-Path $taskRoot $Config}
$configuration = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$logFolder = Join-Path $taskRoot ("Log\{0}" -f $configuration.profile)
New-Item -ItemType Directory -Force -Path $logFolder | Out-Null
$statePath = Join-Path $logFolder 'BaselineWorker.json'
function Write-State([string]$Phase, [int]$Attempt, [int]$Code) {
    [ordered]@{ phase=$Phase; attempt=$Attempt; exitCode=$Code; processId=$PID; updated=(Get-Date).ToUniversalTime().ToString('o'); config=$Config } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}
for ($attempt=1; $attempt -le $MaximumAttempts; $attempt++) {
    Write-State 'SyncRunning' $attempt 0
    $log = Join-Path $logFolder ("BaselineSync{0}Attempt{1}.log" -f (Get-Date -Format 'yyyyMMddTHHmmss'),$attempt)
    $ErrorActionPreference = 'Continue'
    & $ProPython (Join-Path $taskRoot 'Py\BuildEnverusGuggWellRecord.py') sync --config $Config 2>&1 | Tee-Object -FilePath $log
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -eq 0) {
        Write-State 'CreatingTransfer' $attempt 0
        $ErrorActionPreference = 'Continue'
        & $ProPython (Join-Path $taskRoot 'Py\CacheTransfer.py') export --config $Config 2>&1 | Tee-Object -FilePath (Join-Path $logFolder 'BaselineTransfer.log')
        $transferCode=$LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($transferCode -eq 0) { Write-State 'Complete' $attempt 0; exit 0 }
        Write-State 'SyncCompleteTransferFailed' $attempt $transferCode
        exit $transferCode
    }
    if ($code -eq 75) { Write-State 'AnotherRunActive' $attempt $code; exit 75 }
    Write-State 'WaitingToResume' $attempt $code
    if ($attempt -lt $MaximumAttempts) { Start-Sleep -Seconds $RetrySeconds }
}
Write-State 'NeedsAttention' $MaximumAttempts $code
exit $code
