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
$code=$LASTEXITCODE
$ErrorActionPreference='Stop'
$status=if ($code -eq 0) {'Complete'} elseif ($code -eq 75) {'SkippedAnotherRunActive'} elseif ($code -eq 76) {'WaitingForBaselineImport'} elseif ($code -eq 77) {'WaitingForInitialGIS'} else {'Failed'}
@{status=$status;started=$stamp;completed=(Get-Date).ToUniversalTime().ToString('o');action=$action;exitCode=$code;log=$log} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
if ($code -in @(75,76,77)) { exit 0 }
exit $code
