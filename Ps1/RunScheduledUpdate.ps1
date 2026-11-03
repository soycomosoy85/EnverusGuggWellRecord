param(
    [string]$Config = 'Json/Config/Nightly.json',
    [string]$ProPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat'
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$configPath=if ([IO.Path]::IsPathRooted($Config)) {$Config} else {Join-Path $taskRoot $Config}
$cfg=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$action=if ($cfg.nightly.action) { [string]$cfg.nightly.action } else { 'run' }
if ($action -notin @('run','sync','build')) { throw 'Unsupported nightly action.' }
$folder=Join-Path $taskRoot ("Log\{0}" -f $cfg.profile)
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log=Join-Path $folder ("Nightly{0}.log" -f $stamp)
$state=Join-Path $folder 'LatestNightly.json'
@{status='Running';started=$stamp;action=$action;processId=$PID;log=$log} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
$ErrorActionPreference='Continue'
& $ProPython (Join-Path $taskRoot 'Py\BuildEnverusGuggWellRecord.py') $action --config $Config --require-cache 2>&1 | Tee-Object -FilePath $log
$wellCode=$LASTEXITCODE
$contextCode=0
if ($wellCode -in @(0,75,76,77)) {
    & $ProPython (Join-Path $taskRoot 'Py\ContextLayers.py') $action 2>&1 | Tee-Object -FilePath (Join-Path $folder ("NightlyContext{0}.log" -f $stamp))
    $contextCode=$LASTEXITCODE
    & $ProPython (Join-Path $taskRoot 'Py\AgolPreflight.py') --prepare-subset 2>&1 | Tee-Object -FilePath (Join-Path $folder ("NightlyAgolReadiness{0}.log" -f $stamp))
    $readinessCode=$LASTEXITCODE
} else { $readinessCode=0 }
$code=if ($contextCode -notin @(0,75)) {$contextCode} elseif ($readinessCode -ne 0) {$readinessCode} else {$wellCode}
$ErrorActionPreference='Stop'
$status=if ($code -eq 0) {'Complete'} elseif ($code -eq 75) {'SkippedAnotherRunActive'} elseif ($code -eq 76) {'WaitingForBaselineImport'} elseif ($code -eq 77) {'WaitingForInitialGIS'} else {'Failed'}
@{status=$status;started=$stamp;completed=(Get-Date).ToUniversalTime().ToString('o');action=$action;exitCode=$code;wellExitCode=$wellCode;contextExitCode=$contextCode;agolReadinessExitCode=$readinessCode;agolPublishingEnabled=$false;log=$log} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
if ($code -in @(75,76,77)) { exit 0 }
exit $code
