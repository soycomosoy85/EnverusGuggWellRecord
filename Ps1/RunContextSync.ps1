param(
    [string]$ProPython='C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat',
    [int]$MaximumAttempts=12,
    [int]$RetrySeconds=300
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$cfg=Get-Content -LiteralPath (Join-Path $taskRoot 'Json\Config\ContextLayers.json') -Raw | ConvertFrom-Json
$folder=Join-Path $taskRoot ('Log\'+$cfg.profile)
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$state=Join-Path $folder 'ContextWorker.json'
for ($attempt=1;$attempt -le $MaximumAttempts;$attempt++) {
    @{phase='Running';attempt=$attempt;processId=$PID;updated=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
    $ErrorActionPreference='Continue'
    & $ProPython (Join-Path $taskRoot 'Py\ContextLayers.py') run 2>&1 | Tee-Object -FilePath (Join-Path $folder ('ContextAttempt'+$attempt+'.log'))
    $code=$LASTEXITCODE
    $ErrorActionPreference='Stop'
    $phase=if($code -eq 0){'Complete'}elseif($code -eq 75){'AnotherRunActive'}elseif($attempt -eq $MaximumAttempts){'NeedsAttention'}else{'WaitingToRetry'}
    @{phase=$phase;attempt=$attempt;processId=$PID;exitCode=$code;updated=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
    if ($code -in @(0,75)) { exit $code }
    if ($attempt -lt $MaximumAttempts) { Start-Sleep -Seconds $RetrySeconds }
}
exit $code
