<#
Current-user logon task for the previously approved SwimMate analysis PC.
No admin elevation, password storage, sleep-policy changes, or new approval.
Install starts the task now as well as at subsequent interactive logons.
#>
[CmdletBinding()]
param([ValidateSet('Install', 'Connect', 'Status', 'Remove')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskName = 'SwimMate Video Worker - ' + $identity.User.Value
$root = Split-Path -Parent $PSScriptRoot
$arguments = '-X utf8 -m analysis_v2.workbench.background_worker'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$ownerSid = $null
if ($existing) {
    try {
        $owner = $existing.Principal.UserId
        $ownerSid = if ($owner.StartsWith('S-1-')) { $owner } else {
            ([Security.Principal.NTAccount]::new($owner)).Translate([Security.Principal.SecurityIdentifier]).Value
        }
    } catch { throw 'Cannot verify ownership of the existing task. No changes made.' }
}

# Do not overwrite or stop a foreign task even if it happens to share the name.
if ($existing -and ($existing.Actions.Count -ne 1 -or $existing.Actions[0].Arguments -ne $arguments -or
    $ownerSid -ne $identity.User.Value)) {
    throw 'A task with this name is not owned by this SwimMate launcher. No changes made.'
}

if ($Action -eq 'Remove') {
    if ($existing) {
        Stop-ScheduledTask -TaskName $taskName
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Output 'SwimMate automatic startup removed. Saved PC approval was retained.'
    return
}

if ($Action -in @('Install','Connect')) {
    $python = (& python -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Python is not available.' }
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { throw 'A Windows Python installation with pythonw.exe is required.' }
    Push-Location $root
    try {
        if ($Action -eq 'Connect') {
            # Only an explicit repair command requests enrollment. Logon never does.
            & $python -X utf8 -u -m analysis_v2.workbench.remote_worker --enroll-only
            if ($LASTEXITCODE -ne 0) { throw 'PC enrollment was not completed. Automatic startup was not changed.' }
        }
        & $python -c "from analysis_v2.workbench.device_credentials import DeviceCredentials; import sys; sys.exit(0 if DeviceCredentials('https://swimtech.vercel.app').path.exists() else 2)"
        if ($LASTEXITCODE -ne 0 -and -not $existing) { throw 'First approve this PC with the normal worker. No automatic pairing will be created.' }
    } finally { Pop-Location }
    $launch = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
    $trigger.Delay = 'PT15S'
    # A demand-started task does not reliably restart after a process exit on
    # every Windows installation. A periodic trigger also recovers a dead task.
    # IgnoreNew prevents a second healthy worker. Rejected approvals are paused
    # locally, so these probes never repeatedly authenticate a revoked device.
    $watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $launch -Trigger @($trigger,$watchdog) -Principal $principal `
        -Settings $settings -Description 'SwimMate video processing: current-user logon, remembered approval, automatic reconnect. Remove with scripts/video_worker_autostart.ps1 -Action Remove.' -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) { Write-Output 'SwimMate automatic startup is not installed.'; return }
$info = Get-ScheduledTaskInfo -TaskName $taskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = [string]$task.State
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
    LogonTrigger = [bool]($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' })
    TimeLimit = $task.Settings.ExecutionTimeLimit
    BatteryAllowed = -not $task.Settings.DisallowStartIfOnBatteries
    StopOnBattery = $task.Settings.StopIfGoingOnBatteries
    RestartInterval = $task.Settings.RestartInterval
    WatchdogInterval = ($task.Triggers | Where-Object { $_.Repetition.Interval }).Repetition.Interval
    Python = $task.Actions[0].Execute
    WorkingDirectory = $task.Actions[0].WorkingDirectory
    LogPath = Join-Path $env:LOCALAPPDATA 'SwimMate\video-worker\background.log'
} | ConvertTo-Json
