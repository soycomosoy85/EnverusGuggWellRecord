param(
    [ValidateSet('validate','probe','sync','build','run','test','migrate')][string]$Action = 'validate',
    [string]$Config = 'Json/Config/Workflow.json',
    [string]$ProPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat'
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $ProPython)) { throw 'ArcGIS Pro Python was not found. Supply -ProPython with your propy.bat or licensed ArcPy python.exe path.' }
& $ProPython (Join-Path $taskRoot 'Py\BuildEnverusGuggWellRecord.py') $Action --config $Config
if ($LASTEXITCODE -ne 0) { throw "Well record $Action failed with exit code $LASTEXITCODE." }
