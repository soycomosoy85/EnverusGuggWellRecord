param(
    [string]$OutputRoot,
    [string]$ProPython='C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
)
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
if (-not $OutputRoot) {$OutputRoot=Join-Path $sourceRoot 'CustomRuns\TexasNewMexico'}
$logFolder=Join-Path $OutputRoot 'Log\TexasNewMexico'
New-Item -ItemType Directory -Force -Path $logFolder | Out-Null
$state=Join-Path $logFolder 'CustomRun.json'
function Write-State([string]$Phase,[int]$Code) {
    @{phase=$Phase;exitCode=$Code;processId=$PID;updated=(Get-Date).ToUniversalTime().ToString('o');outputRoot=$OutputRoot} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
}
Write-State 'PreparingAndBuildingCachedSubset' 0
$ErrorActionPreference='Continue'
& $ProPython -u (Join-Path $sourceRoot 'Py\BuildCachedSubset.py') --source-root $sourceRoot --output-root $OutputRoot 2>&1 | Tee-Object -FilePath (Join-Path $logFolder 'CustomRun.log')
$code=$LASTEXITCODE
$ErrorActionPreference='Stop'
Write-State $(if($code -eq 0){'Complete'}else{'NeedsAttention'}) $code
exit $code
