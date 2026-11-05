param(
    [Parameter(Mandatory=$true)][string]$Root,
    [string]$ProPython='C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
)
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
$statePath=Join-Path $Root 'Log\TexasNewMexico\CustomRun.json'
$logPath=Join-Path $Root 'Log\TexasNewMexico\ConstraintAttributeAmendment.log'
@{phase='ApplyingAttributesThenPauseForQc';processId=$PID;exitCode=0;updated=(Get-Date).ToUniversalTime().ToString('o');exportShapefiles=$false} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
$ErrorActionPreference='Continue'
& $ProPython -u (Join-Path $sourceRoot 'Py\ApplyConstraintAmendment.py') --root $Root 2>&1 | Tee-Object -FilePath $logPath
$code=$LASTEXITCODE
$ErrorActionPreference='Stop'
if ($code -ne 0) {
    @{phase='NeedsAttention';exitCode=$code;updated=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    exit $code
}
$upgrade=Get-Content -LiteralPath (Join-Path $Root 'Json\TexasNewMexico\Output\Qa\ConstraintAttributeUpgrade.json') -Raw | ConvertFrom-Json
if ($upgrade.status -ne 'Complete' -or -not $upgrade.validation.passed) {throw 'The constraint attribute amendment did not pass validation.'}
$counts=@{}
foreach ($property in $upgrade.features.PSObject.Properties) {$counts[$property.Name]=$property.Value.count}
$report=@{status='PausedForQc';geodatabase=$upgrade.geodatabase;counts=$counts;validation=$upgrade.validation;exportShapefiles=$false;unfinishedLayers=@('EnvSH_Gugg');attributeUpgrade=$upgrade;updated=(Get-Date).ToUniversalTime().ToString('o')}
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $Root 'Json\Config\TxNmQcOutput.json') -Encoding UTF8
@{phase='PausedForQc';exitCode=0;counts=$counts;unfinishedLayers=@('EnvSH_Gugg');updated=(Get-Date).ToUniversalTime().ToString('o');exportShapefiles=$false} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
