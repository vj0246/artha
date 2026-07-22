<#
.SYNOPSIS
    Register (or repair) every Artha scheduled task. Idempotent.

.DESCRIPTION
    Run from an ordinary PowerShell prompt:

        powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1

    WHY THIS SCRIPT EXISTS (2026-07-22): the tasks were originally created
    with `schtasks /TR "<quoted path>"`. The shell stripped the quotes, so
    Windows stored a repo path containing spaces as
        Execute   = C:\Users\vivaa\OneDrive\Desktop\Personal
        Arguments = Projects\Quant\artha\scripts\artha_daily.cmd
    and every run failed with 0x80070002 (file not found). The failure was
    silent for three days — the tasks showed "Ready", they simply never
    did anything — until the heartbeat's staleness alarm caught it.

    The fix is structural: invoke cmd.exe with the wrapper as a quoted
    ARGUMENT, so no path is ever parsed as an executable, and set an
    explicit working directory.

    It also sets the power/availability options that matter on a laptop:
      StartWhenAvailable      - run a missed task as soon as possible
      AllowStartIfOnBatteries - do not skip the run on battery
      DontStopIfGoingOnBatteries
    Without these, unplugging the machine silently stops the B1 clock.

    NOT enabled: WakeToRun. Waking a sleeping laptop at 19:00 every day is
    the user's call, not a default this script should impose. Enable it in
    Task Scheduler if you want the machine to wake itself.
#>

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$scripts = Join-Path $repo "scripts"

$tasks = @(
    @{ Name = "artha-daily";     Wrapper = "artha_daily.cmd";     Trigger = "daily";     Time = "19:00" },
    @{ Name = "artha-heartbeat"; Wrapper = "artha_heartbeat.cmd"; Trigger = "daily";     Time = "21:00" },
    @{ Name = "artha-weekly";    Wrapper = "artha_weekly.cmd";    Trigger = "weekly";    Time = "10:00" },
    @{ Name = "artha-monthly";   Wrapper = "artha_monthly.cmd";   Trigger = "monthly";   Time = "10:00" },
    @{ Name = "artha-quarterly"; Wrapper = "artha_quarterly.cmd"; Trigger = "quarterly"; Time = "10:00" }
)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

# S4U = "run whether the user is logged on or not", without storing a password.
# Preferred: an Interactive-logon task is bound to the desktop session, so a long
# cycle can die with 0xC000013A (Ctrl+C) when that session is torn down. The daily
# cycle needs no desktop — it writes files and calls the network.
#
# S4U requires SeTcbPrivilege, i.e. an ELEVATED prompt. Run this script as
# Administrator once to get the robust principal; unelevated it falls back to
# Interactive, which works while you are logged in and is what we had before.
function New-ArthaPrincipal {
    try {
        return New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
    } catch {
        return $null
    }
}
$principal = New-ArthaPrincipal
$fallback = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

foreach ($t in $tasks) {
    $wrapper = Join-Path $scripts $t.Wrapper
    if (-not (Test-Path $wrapper)) { throw "missing wrapper: $wrapper" }

    # cmd.exe is the executable; the space-containing path is a quoted ARGUMENT.
    $action = New-ScheduledTaskAction -Execute "cmd.exe" `
        -Argument ('/c "' + $wrapper + '"') -WorkingDirectory $repo

    $trigger = switch ($t.Trigger) {
        "daily"     { New-ScheduledTaskTrigger -Daily -At $t.Time }
        "weekly"    { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At $t.Time }
        "monthly"   { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -WeeksInterval 4 -At $t.Time }
        "quarterly" { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -WeeksInterval 12 -At $t.Time }
    }

    # -Force overwrites in place. Never Unregister-then-Register: if the second
    # half fails (S4U needs elevation) the task is left DELETED, not merely stale.
    $used = "S4U"
    $ok = $false
    if ($principal) {
        try {
            Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
                -Settings $settings -Principal $principal -Force `
                -Description "Artha $($t.Name) - see docs/RUNBOOK.md" | Out-Null
            $ok = $true
        } catch { $ok = $false }
    }
    if (-not $ok) {
        $used = "Interactive (not elevated - see header)"
        Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
            -Settings $settings -Principal $fallback -Force `
            -Description "Artha $($t.Name) - see docs/RUNBOOK.md" | Out-Null
    }

    $stored = (Get-ScheduledTask -TaskName $t.Name).Actions[0]
    Write-Host ("{0,-18} OK  logon={1}  execute={2}" -f $t.Name, $used, $stored.Execute)
}

Write-Host ""
Write-Host "Verify a task actually runs (not just 'Ready'):"
Write-Host "  schtasks /Run /TN artha-heartbeat"
Write-Host "  Get-ScheduledTaskInfo artha-heartbeat | Select LastTaskResult   # 0 = success"
