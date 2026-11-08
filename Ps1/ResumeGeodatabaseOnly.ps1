param([string]$ProPython='C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$folder=Join-Path $root 'Log\NorthAmerica'
$state=Join-Path $folder 'RevisionWorker.json'
function Write-State([string]$Phase,[int]$Code) {
    @{phase=$Phase;exitCode=$Code;processId=$PID;updated=(Get-Date).ToUniversalTime().ToString('o');runtime=$root;outputFormat='FileGeodatabase'} | ConvertTo-Json | Set-Content -LiteralPath $state -Encoding UTF8
}
Write-State 'CompletingSurfaceHolesFromGdbCheckpoint' 0
$ErrorActionPreference='Continue'
& $ProPython (Join-Path $root 'Py\ResumeGeodatabaseCheckpoint.py') 2>&1 | Tee-Object -FilePath (Join-Path $folder 'RevisionGdbOnlyResume.log')
$code=$LASTEXITCODE
$ErrorActionPreference='Stop'
if ($code -ne 0) {Write-State 'GdbCheckpointNeedsAttention' $code;exit $code}
Write-State 'ValidatingNationalOutputs' 0
$ErrorActionPreference='Continue'
& $ProPython (Join-Path $root 'Py\ValidateNationalOutputs.py') 2>&1 | Tee-Object -FilePath (Join-Path $folder 'RevisionValidation.log')
$code=$LASTEXITCODE
$ErrorActionPreference='Stop'
Write-State $(if($code -eq 0){'Complete'}else{'ValidationNeedsAttention'}) $code
exit $code
