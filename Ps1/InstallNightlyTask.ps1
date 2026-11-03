[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [string]$Config = 'Json/Config/Nightly.json',
    [string]$ProPython = 'C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\propy.bat',
    [string]$Time,
    [switch]$RunWhenLoggedOff,
    [switch]$Preview,
    [switch]$Remove
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$configPath=if ([IO.Path]::IsPathRooted($Config)) {$Config} else {Join-Path $taskRoot $Config}
$cfg=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if (-not $Time) { $Time=if ($cfg.nightly.time) {[string]$cfg.nightly.time} else {'01:00'} }
$clock=[datetime]::ParseExact($Time,'HH:mm',[Globalization.CultureInfo]::InvariantCulture)
if ($clock -le (Get-Date)) { $clock=$clock.AddDays(1) }
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$name='BuildEnverusGuggWellRecord-'+$cfg.profile
$shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$script=Join-Path $taskRoot 'Ps1\RunScheduledUpdate.ps1'
if ($Config.Contains('"') -or $ProPython.Contains('"') -or $script.Contains('"')) { throw 'Paths cannot contain quote characters.' }
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -Config "{1}" -ProPython "{2}"' -f $script,$Config,$ProPython
$plan=[ordered]@{taskName=$name;time=$Time;firstTrigger=$clock.ToString('s');timeZone=(Get-TimeZone).Id;action=$cfg.nightly.action;user=$user;logonType=$(if($RunWhenLoggedOff){'Password'}else{'Interactive'});command=$shell;arguments=$arguments;workingDirectory=$taskRoot;overlapPolicy='IgnoreNew';catchUpMissedRuns=$true;retryCount=3;retryMinutes=15;wakeToRun=$true}
if ($Preview) { $plan | ConvertTo-Json; return }
if ($Remove) {
    if ($PSCmdlet.ShouldProcess($name,'Remove this well-record scheduled task')) { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
    return
}
if (-not (Test-Path -LiteralPath $ProPython)) { throw 'ArcGIS Pro Python not found; supply -ProPython.' }
$action=New-ScheduledTaskAction -Execute $shell -Argument $arguments -WorkingDirectory $taskRoot
$trigger=New-ScheduledTaskTrigger -Daily -At $clock
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit ([TimeSpan]::Zero)
$logon=if($RunWhenLoggedOff){'Password'}else{'Interactive'}
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType $logon -RunLevel Limited
$definition=New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description ('Gugg Build Enverus Gugg Well Record nightly update: '+$taskRoot)
if ($PSCmdlet.ShouldProcess($name,'Register or update the nightly well-record task')) {
    $existing=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing -and -not $existing.Description.StartsWith('Gugg Build Enverus Gugg Well Record nightly update:')) { throw 'An unrelated task has this name; it was not changed.' }
    if ($RunWhenLoggedOff) {
        $credential=Get-Credential -UserName $user -Message 'Windows Task Scheduler credentials for this work-machine user. The password is not saved in project files.'
        Register-ScheduledTask -TaskName $name -InputObject $definition -User $credential.UserName -Password ($credential.GetNetworkCredential().Password) -Force | Out-Null
    } else { Register-ScheduledTask -TaskName $name -InputObject $definition -Force | Out-Null }
    $plan | ConvertTo-Json
}
