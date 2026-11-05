param(
    [Parameter(Mandatory=$true)][string]$CustomRoot,
    [string]$NationalRoot,
    [string]$ProPython='C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe'
)
$ErrorActionPreference='Stop'
$sourceRoot=Split-Path -Parent $PSScriptRoot
$customState=Join-Path $CustomRoot 'Log\TexasNewMexico\CustomRun.json'
$marker=Join-Path $CustomRoot 'Json\Config\ConstraintAttributeAmendment.json'
$log=Join-Path $CustomRoot 'Log\TexasNewMexico\ConstraintAttributeAmendment.log'
@{status='WaitingForBuild';processId=$PID;updated=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
try {
    while ($true) {
        $state=Get-Content -LiteralPath $customState -Raw | ConvertFrom-Json
        if ($state.phase -eq 'Complete') {break}
        if ($state.phase -eq 'NeedsAttention') {throw 'The TX/NM build needs attention; the attribute amendment has not run.'}
        Start-Sleep -Seconds 30
    }
    $targets=@($CustomRoot)
    if ($NationalRoot) {$targets+= $NationalRoot}
    foreach ($targetRoot in $targets) {
        do {
            $ErrorActionPreference='Continue'
            & $ProPython -u (Join-Path $sourceRoot 'Py\ApplyConstraintAmendment.py') --root $targetRoot 2>&1 | Tee-Object -FilePath $log -Append
            $code=$LASTEXITCODE
            $ErrorActionPreference='Stop'
            if ($code -eq 75) {Start-Sleep -Seconds 30}
        } while ($code -eq 75)
        if ($code -ne 0) {throw "Constraint amendment failed for $targetRoot with exit code $code; see $log"}
    }
} catch {
    $prior=Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($prior.status -ne 'Complete') {
        @{status='NeedsAttention';error=$_.Exception.Message;updated=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
    }
    throw
}
