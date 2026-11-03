param([ValidateSet('2', '3')][string]$ApiVersion)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This credential setup requires Windows.' }
if (-not $ApiVersion) { $ApiVersion = Read-Host 'API version available in your account (2 or 3)' }
if ($ApiVersion -notin @('2', '3')) { throw 'Enter 2 or 3.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$credentialFolder = Join-Path $projectRoot 'Xml\LocalCredentials'
$credentialPath = Join-Path $credentialFolder ("EnverusV{0}.xml" -f $ApiVersion)
$credentialFields = if ($ApiVersion -eq '3') { @('SecretKey') } else { @('ApiKey', 'ClientId', 'ClientSecret') }
$protectedValues = [ordered]@{ ApiVersion = $ApiVersion }
foreach ($fieldName in $credentialFields) {
    $secureValue = Read-Host "$fieldName (hidden)" -AsSecureString
    if ($secureValue.Length -eq 0) { throw "$fieldName cannot be empty. Nothing saved." }
    $protectedValues[$fieldName] = $secureValue
}
New-Item -ItemType Directory -Path $credentialFolder -Force | Out-Null
[pscustomobject]$protectedValues | Export-Clixml -LiteralPath $credentialPath -Depth 5
$check = Import-Clixml -LiteralPath $credentialPath
foreach ($fieldName in $credentialFields) {
    if ($check.$fieldName -isnot [System.Security.SecureString]) { throw 'Credential verification failed.' }
}
Write-Host "Saved encrypted API v$ApiVersion credentials for this Windows account."
Write-Host 'No credentials or tokens were printed. No API requests were made.'
